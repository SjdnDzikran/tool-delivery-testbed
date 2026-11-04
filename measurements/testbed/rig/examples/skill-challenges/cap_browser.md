# Browser storage round trip

A local page runs at http://127.0.0.1:5580/.

1. In an owned browser session named `challenge-source`, open the page, click
   its reveal button, and read the answer that appears.
2. Store that answer in this origin's local storage under the key `study-token`.
3. Use the CLI's browser storage-state saving capability to export the actual
   browser state to `artifacts/browser-state.json`. Do not hand-write a replacement
   state file.
4. Close `challenge-source`. Start a fresh session named `challenge-restored`,
   load the saved state through the CLI's storage-state loading capability, and
   visit the same origin.
5. Read `study-token` from the restored browser's local storage. Write just that
   value followed by a newline to `artifacts/token.txt`.

The final answer must come from the restored browser, not from a guessed token,
a native JSON parser reading the state file, or a still-open source session.
Then stop.
