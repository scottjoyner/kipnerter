"use client";

const MAX_DRAFT_CHARS = 4000;

/**
 * Visible, accessible, client-only chat composition surface.
 *
 * Deliberately no transport: authenticated user-bound model admission,
 * execution receipts, and cancel/replay semantics have not been approved.
 * A draft is kept only in the parent React component's memory.
 */
export default function ChatComposer({ draft, onDraftChange }) {
  function discardDraft() {
    if (draft.trim() && !window.confirm("Discard this unsent message draft?")) return;
    onDraftChange("");
  }

  return <div className="chat-compose-shell">
    <form className="chat-compose-form" onSubmit={event => event.preventDefault()}>
      <label htmlFor="kipnerter-message-draft" className="chat-compose-label">Your message</label>
      <textarea
        id="kipnerter-message-draft"
        className="chat-compose-input"
        value={draft}
        onChange={event => onDraftChange(event.target.value)}
        maxLength={MAX_DRAFT_CHARS}
        rows={4}
        spellCheck
        placeholder="Compose a message… (not sent until fleet admission is enabled)"
        aria-describedby="kipnerter-draft-custody"
      />
      <div className="chat-compose-actions">
        <button type="button" className="chat-compose-reset" onClick={discardDraft}>
          New draft
        </button>
        <span className="chat-compose-count">{draft.length} / {MAX_DRAFT_CHARS}</span>
        <button type="submit" className="chat-compose-send" disabled
          title="Authenticated execution and per-user model receipts are not yet approved">
          Send unavailable
        </button>
      </div>
    </form>
    <p id="kipnerter-draft-custody" className="chat-compose-custody" role="status">
      Draft only — never transmitted, saved to disk, or counted as a conversation.
      Switching workspace tabs preserves this draft; closing or reloading the page clears it.
    </p>
  </div>;
}
