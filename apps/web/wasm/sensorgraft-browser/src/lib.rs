//! Browser-only, bounded ephemeral Rust cosine index. Persistence is provided by
//! IndexedDB in the hosting application. This is not the complete SensorGraft DB.
use std::alloc::{alloc, dealloc, Layout};
use std::sync::Mutex;

const DIM: usize = 128;
const MAX_RECORDS: usize = 512;
const MAX_RESULTS: usize = 8;

#[derive(Clone)]
struct Entry { id: u32, vector: [f32; DIM] }
static INDEX: Mutex<Vec<Entry>> = Mutex::new(Vec::new());

#[unsafe(no_mangle)]
pub extern "C" fn sg_alloc(bytes: usize) -> *mut u8 {
    if bytes == 0 || bytes > 4096 { return std::ptr::null_mut(); }
    let Ok(layout) = Layout::from_size_align(bytes, 4) else { return std::ptr::null_mut(); };
    // SAFETY: allocation is released with an identical Layout in sg_free.
    unsafe { alloc(layout) }
}
#[unsafe(no_mangle)]
pub extern "C" fn sg_free(ptr: *mut u8, bytes: usize) {
    if ptr.is_null() || bytes == 0 || bytes > 4096 { return; }
    if let Ok(layout) = Layout::from_size_align(bytes, 4) {
        // SAFETY: caller must pass a pointer returned by sg_alloc and the same size.
        unsafe { dealloc(ptr, layout); }
    }
}
#[unsafe(no_mangle)]
pub extern "C" fn sg_reset() {
    if let Ok(mut index) = INDEX.lock() { index.clear(); }
}
fn read_vector(ptr: *const f32, len: usize) -> Option<[f32; DIM]> {
    if ptr.is_null() || len != DIM { return None; }
    // SAFETY: host owns exactly DIM contiguous f32 bytes at ptr.
    let values = unsafe { std::slice::from_raw_parts(ptr, DIM) };
    if values.iter().any(|v| !v.is_finite()) { return None; }
    let mut vector = [0f32; DIM];
    vector.copy_from_slice(values);
    let norm = vector.iter().map(|v| v * v).sum::<f32>().sqrt();
    if norm <= 1e-6 { return None; }
    for v in &mut vector { *v /= norm; }
    Some(vector)
}
#[unsafe(no_mangle)]
pub extern "C" fn sg_insert(id: u32, ptr: *const f32, len: usize) -> i32 {
    if id == 0 { return -1; }
    let Some(vector) = read_vector(ptr, len) else { return -2; };
    let Ok(mut index) = INDEX.lock() else { return -3; };
    if let Some(existing) = index.iter_mut().find(|e| e.id == id) {
        existing.vector = vector;
    } else {
        if index.len() >= MAX_RECORDS { index.remove(0); }
        index.push(Entry { id, vector });
    }
    0
}
#[unsafe(no_mangle)]
pub extern "C" fn sg_search(
    ptr: *const f32, len: usize, result_ptr: *mut u32,
    result_capacity: usize, excluded_id: u32,
) -> u32 {
    if result_ptr.is_null() || result_capacity == 0 || result_capacity > MAX_RESULTS { return 0; }
    let Some(query) = read_vector(ptr, len) else { return 0; };
    let Ok(index) = INDEX.lock() else { return 0; };
    let mut ranked: Vec<(u32, f32)> = index.iter()
        .filter(|e| e.id != excluded_id)
        .map(|e| (e.id, query.iter().zip(e.vector.iter()).map(|(a, b)| a * b).sum::<f32>()))
        .filter(|(_, similarity)| *similarity >= 0.18)
        .collect();
    ranked.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    let count = ranked.len().min(result_capacity);
    // SAFETY: host provided a writable result buffer for result_capacity u32 values.
    let output = unsafe { std::slice::from_raw_parts_mut(result_ptr, result_capacity) };
    for (out, (id, _)) in output.iter_mut().zip(ranked.into_iter()).take(count) { *out = id; }
    count as u32
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cosine_index_rejects_invalid_and_ranks() {
        sg_reset();
        let mut v = [0.0; DIM]; v[0] = 1.0;
        assert_eq!(sg_insert(1, v.as_ptr(), DIM), 0);
        assert_eq!(sg_insert(2, std::ptr::null(), DIM), -2);
        let mut w = [0.0; DIM]; w[1] = 1.0;
        assert_eq!(sg_insert(3, w.as_ptr(), DIM), 0);
        let mut hits = [0u32; 3];
        assert_eq!(sg_search(v.as_ptr(), DIM, hits.as_mut_ptr(), 3, 0), 1);
        assert_eq!(hits[0], 1);
        assert_eq!(sg_search(v.as_ptr(), DIM, hits.as_mut_ptr(), 3, 1), 0);
    }
}
