"""A single self-contained page for managing the word list, served at /manage.

No build step and no dependencies. It talks to the same API as everything else, so it
follows the same rules: uploading needs the WOTD_ADMIN_TOKEN, which is typed into the
page each time and never stored.
"""

# Content-Security-Policy: inline script/style are the page itself; nothing else may load.
CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'"
)

MANAGE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Word of the Day: word list</title>
<style>
  :root { color-scheme: light dark; --bg:#fff; --fg:#1c1c1e; --muted:#6b6b70; --card:#f4f4f6;
          --line:#d8d8dc; --accent:#2f6fed; --ok:#1a7f37; --bad:#c62828; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161618; --fg:#ececee; --muted:#9a9aa1; --card:#202024; --line:#38383d;
            --accent:#6c9cff; --ok:#4cc46b; --bad:#ff6b6b; } }
  body { font: 16px/1.5 system-ui, sans-serif; background: var(--bg); color: var(--fg);
         max-width: 40rem; margin: 2rem auto; padding: 0 1rem; }
  h1 { font-size: 1.4rem; margin-bottom: .2rem; }
  p.sub { color: var(--muted); margin-top: 0; }
  section { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
            padding: 1rem; margin: 1rem 0; }
  h2 { font-size: 1rem; margin: 0 0 .5rem; }
  #today { font-size: 1.6rem; font-weight: 600; }
  #meaning { color: var(--muted); margin: .2rem 0 0; }
  label { display: block; font-size: .85rem; color: var(--muted); margin: .8rem 0 .25rem; }
  textarea, input[type=password] { width: 100%; box-sizing: border-box; padding: .5rem;
      font: inherit; color: inherit; background: var(--bg); border: 1px solid var(--line);
      border-radius: 6px; }
  textarea { min-height: 10rem; font-family: ui-monospace, monospace; font-size: .9rem; }
  .row { display: flex; gap: .5rem; flex-wrap: wrap; margin-top: .8rem; }
  button { font: inherit; padding: .5rem .9rem; border-radius: 6px; cursor: pointer;
           border: 1px solid var(--line); background: var(--bg); color: inherit; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button:disabled { opacity: .5; cursor: default; }
  #status { min-height: 1.4rem; margin-top: .6rem; }
  .ok { color: var(--ok); } .bad { color: var(--bad); }
  #list, #shown-list { columns: 2; margin: .5rem 0 0; padding-left: 1.2rem; font-size: .9rem; }
  details summary { cursor: pointer; }
</style>
</head>
<body>
<h1>Word of the Day</h1>
<p class="sub">Manage the list of words it chooses from.</p>

<section>
  <h2>Today</h2>
  <div id="today">…</div>
  <p id="meaning"></p>
</section>

<section>
  <h2>Upload words</h2>
  <label for="file">Text file, one word per line (or type/paste below)</label>
  <input id="file" type="file" accept=".txt,text/plain">
  <label for="words">Words</label>
  <textarea id="words" spellcheck="false"
    placeholder="serendipity&#10;ephemeral&#10;# lines starting with # are ignored"></textarea>
  <label for="token">Admin token (WOTD_ADMIN_TOKEN)</label>
  <input id="token" type="password" autocomplete="off">
  <div class="row">
    <button class="primary" id="replace">Replace list</button>
    <button id="add">Add to list</button>
    <button id="edit" title="Fill the box with the current list so you can edit it">
      Edit current list
    </button>
  </div>
  <div id="status" role="status"></div>
</section>

<section>
  <details id="shown">
    <summary><span id="shown-count">Previously shown</span></summary>
    <ul id="shown-list"></ul>
  </details>
</section>

<section>
  <details id="current">
    <summary><span id="count">Current list</span></summary>
    <ul id="list"></ul>
  </details>
</section>

<script>
const $ = (id) => document.getElementById(id);

async function load() {
  try {
    const [word, list, shown] = await Promise.all([
      fetch("/widget").then((r) => r.json()),
      fetch("/word-list").then((r) => r.json()),
      fetch("/recent?days=365").then((r) => r.json()),
    ]);
    $("shown-count").textContent = `Previously shown (${shown.length})`;
    $("shown-list").replaceChildren(...shown.map((s) => {
      const li = document.createElement("li");
      li.textContent = `${s.date}  ${s.word}`;
      return li;
    }));
    $("today").textContent = word.word || "";
    $("meaning").textContent = word.definition || "";
    showList(list);
  } catch (e) {
    $("today").textContent = "Couldn't load today's word";
  }
}

function showList(list) {
  $("count").textContent = `Current list (${list.count} words)`;
  const ul = $("list");
  ul.replaceChildren(...list.words.map((w) => {
    const li = document.createElement("li");
    li.textContent = w;
    return li;
  }));
}

function status(text, ok) {
  const el = $("status");
  el.textContent = text;
  el.className = ok ? "ok" : "bad";
}

$("file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (file) $("words").value = await file.text();
});

async function upload(mode) {
  const body = $("words").value;
  if (!body.trim()) return status("Choose a file or type some words first.", false);
  if (!$("token").value) return status("Enter the admin token.", false);
  if (mode === "replace" && !confirm("Replace the whole word list?")) return;
  const buttons = document.querySelectorAll("button");
  buttons.forEach((b) => (b.disabled = true));
  try {
    const res = await fetch(`/word-list?mode=${mode}`, {
      method: "PUT",
      headers: { Authorization: "Bearer " + $("token").value, "Content-Type": "text/plain" },
      body,
    });
    const data = await res.json();
    if (!res.ok) return status(data.detail || `Failed (${res.status})`, false);
    status(mode === "add" ? `Added ${data.added} new word(s). ${data.count} in the list.`
                          : `List replaced: ${data.count} words.`, true);
    $("words").value = "";
    $("file").value = "";
    load();
  } catch (e) {
    status("Couldn't reach the server.", false);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

$("edit").addEventListener("click", async () => {
  const list = await fetch("/word-list").then((r) => r.json());
  $("words").value = list.words.join("\n") + "\n";
  status("Edit the words, then click Replace list.", true);
});

$("replace").addEventListener("click", () => upload("replace"));
$("add").addEventListener("click", () => upload("add"));
load();
</script>
</body>
</html>
"""
