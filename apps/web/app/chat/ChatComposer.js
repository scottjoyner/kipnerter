"use client";

const MAX_DRAFT_CHARS = 4000;

/** No transport. Only the parent-local deterministic telemetry summarizer receives text. */
export default function ChatComposer({ draft, onDraftChange, onSend }) {
  function discardDraft() {
    if (draft.trim() && !window.confirm("Discard this unsent message draft?")) return;
    onDraftChange("");
  }
  function submit(event) {
    event.preventDefault();
    if (!draft.trim()) return;
    onSend(draft);
  }

  return <div className="chat-compose-shell">
    <form className="chat-compose-form" onSubmit={submit}>
      <label htmlFor="kipnerter-message-draft" className="chat-compose-label">Ask about your fleet</label>
      <textarea
        id="kipnerter-message-draft"
        className="chat-compose-input"
        value={draft}
        onChange={event => onDraftChange(event.target.value)}
        maxLength={MAX_DRAFT_CHARS}
        rows={4}
        spellCheck={false}
        placeholder="List offline nodes. What models are reported on xwing?"
        aria-describedby="kipnerter-draft-custody"
      />
      <div className="chat-compose-actions">
        <button type="button" className="chat-compose-reset" onClick={discardDraft}>Clear draft</button>
        <span className="chat-compose-count">{draft.length} / {MAX_DRAFT_CHARS}</span>
        <button type="submit" className="chat-compose-send" disabled={!draft.trim()}>Ask fleet →</button>
      </div>
    </form>
    <p id="kipnerter-draft-custody" className="chat-compose-custody" role="status">
      Questions are answered from already received authenticated read-only snapshots, not a language model.
      Messages remain in this browser tab's memory and are not transmitted or archived.
      Commands, execution, model routing and mutations are unavailable.
    </p>
  </div>;
}
