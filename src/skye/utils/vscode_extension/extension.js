// Skye (.skye language) for VS Code: live diagnostics from `skye check --format json`.
//
// Plain CommonJS, no dependencies, no build step. The extension runs the Skye CLI (setting
// `skye.command`) on the text of the editor, sent on stdin, and turns every item of the JSON
// answer {"diagnostics": [{file, line, column, reason, fix, message}]} into an error squiggle.
"use strict";

const vscode = require("vscode");
const childProcess = require("child_process");
const os = require("os");
const path = require("path");

const DEBOUNCE_MS = 300;
// The token under a diagnostic: a string, a dotted name or a number.
const TOKEN = /"(?:[^"\\]|\\.)*"|[A-Za-z_][\w.]*|\d+(?:\.\d+)?/;

let collection; // vscode.DiagnosticCollection
let warned = false; // the "command not found" warning is shown once per session
const timers = new Map(); // uri -> pending debounce timer
const running = new Map(); // uri -> { child, id } of the check in progress
let nextId = 0;

/** True for the documents this extension checks. */
function isSkye(document) {
  return document.languageId === "skye" && ["file", "untitled"].includes(document.uri.scheme);
}

/** The settings of the `skye` section, for the folder of the document. */
function settings(document) {
  const config = vscode.workspace.getConfiguration("skye", document.uri);
  const command = config.get("command");
  return {
    command: Array.isArray(command) && command.length ? command : ["skye"],
    run: config.get("run") === "onSave" ? "onSave" : "onType",
    registry: config.get("registry") || [],
  };
}

/** The working directory: the workspace folder of the document, else its own directory. */
function workingDirectory(document) {
  const folder = vscode.workspace.getWorkspaceFolder(document.uri);
  if (folder) return folder.uri.fsPath;
  if (document.uri.scheme === "file") return path.dirname(document.fileName);
  const first = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  return first ? first.uri.fsPath : os.tmpdir();
}

/** The range of a diagnostic: from (line, column), 1-based, to the end of the token there. */
function rangeOf(document, line, column) {
  const row = Math.min(Math.max((Number(line) || 1) - 1, 0), Math.max(document.lineCount - 1, 0));
  const text = document.lineAt(row).text;
  const col = Math.min(Math.max((Number(column) || 1) - 1, 0), text.length);
  const start = new vscode.Position(row, col);
  const word = document.getWordRangeAtPosition(start, TOKEN);
  const end = word && word.end.character > col ? word.end : new vscode.Position(row, text.length);
  return new vscode.Range(start, end);
}

/** Show once per session that the CLI could not be run, with a button to the setting. */
function warnOnce(detail) {
  if (warned) return;
  warned = true;
  const open = "Open settings";
  vscode.window
    .showWarningMessage(
      `Skye: the \`skye\` command was not found or failed (${detail}). ` +
        "Set `skye.command`, for example [\"uv\", \"run\", \"skye\"].",
      open
    )
    .then((choice) => {
      if (choice === open) vscode.commands.executeCommand("workbench.action.openSettings", "skye.command");
    });
}

/** Run `skye check` on a document and publish its diagnostics. */
function check(document) {
  if (!isSkye(document)) return;
  const key = document.uri.toString();
  const previous = running.get(key);
  if (previous) previous.child.kill(); // a newer check replaces the one still running
  const { command, registry } = settings(document);
  const args = [
    ...command.slice(1),
    "check", "--format", "json", "--stdin-filename", document.fileName,
    ...(registry.length ? ["--registry", registry.join(",")] : []),
    "-",
  ];
  const id = ++nextId;
  let child;
  try {
    child = childProcess.spawn(command[0], args, { cwd: workingDirectory(document), shell: false });
  } catch (error) {
    collection.delete(document.uri);
    warnOnce(error.message);
    return;
  }
  running.set(key, { child, id });
  const current = () => running.get(key) && running.get(key).id === id;
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => (stdout += chunk));
  child.stderr.on("data", (chunk) => (stderr += chunk));
  child.on("error", (error) => {
    if (!current()) return;
    running.delete(key);
    collection.delete(document.uri);
    warnOnce(error.code === "ENOENT" ? `${command[0]}: not found` : error.message);
  });
  child.on("close", (code) => {
    if (!current()) return; // killed or superseded: a newer check will answer
    running.delete(key);
    // 0 = no mistakes, 1 = mistakes found; anything else means the CLI itself failed.
    if (code !== 0 && code !== 1) {
      collection.delete(document.uri);
      warnOnce(`exit code ${code}${stderr ? ": " + stderr.trim().split("\n").pop() : ""}`);
      return;
    }
    let items;
    try {
      items = JSON.parse(stdout).diagnostics;
      if (!Array.isArray(items)) throw new Error("no diagnostics list");
    } catch (error) {
      collection.delete(document.uri);
      warnOnce(`invalid JSON output: ${error.message}`);
      return;
    }
    collection.set(
      document.uri,
      items.flatMap((item) => {
        // A mistake in a partial file that this document includes is shown at the first use site (`via`) that is in this document.
        const elsewhere = item.file && item.file !== document.fileName;
        const site = elsewhere ? (item.via || []).find((s) => s.file === document.fileName) : null;
        if (elsewhere && !site) return []; // that file's own check shows it
        const where = site || item;
        const prefix = site ? `in ${item.file}:${item.line}:${item.column}: ` : "";
        const message = item.fix ? `${item.reason}\n${item.fix}` : String(item.reason || item.message || "");
        const diagnostic = new vscode.Diagnostic(
          rangeOf(document, where.line, where.column),
          prefix + message,
          vscode.DiagnosticSeverity.Error
        );
        diagnostic.source = "skye";
        return [diagnostic];
      })
    );
  });
  child.stdin.on("error", () => {}); // the process may exit before reading all of stdin
  child.stdin.end(document.getText(), "utf8");
}

/** "Format Document": run `skye fmt -` and replace the text; a file with mistakes is left as it is. */
function format(document) {
  const { command } = settings(document);
  const args = [...command.slice(1), "fmt", "--stdin-filename", document.fileName, "-"];
  return new Promise((resolve) => {
    let child;
    try {
      child = childProcess.spawn(command[0], args, { cwd: workingDirectory(document), shell: false });
    } catch (error) {
      warnOnce(error.message);
      return resolve([]);
    }
    let stdout = "";
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.on("error", (error) => {
      warnOnce(error.code === "ENOENT" ? `${command[0]}: not found` : error.message);
      resolve([]);
    });
    child.on("close", (code) => {
      // 0 = formatted text on stdout; 1 = the file has mistakes (shown by the check), nothing to change.
      if (code !== 0 || stdout === document.getText()) return resolve([]);
      const all = new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length));
      resolve([vscode.TextEdit.replace(all, stdout)]);
    });
    child.stdin.on("error", () => {});
    child.stdin.end(document.getText(), "utf8");
  });
}

/** Check after a pause in typing. */
function schedule(document) {
  const key = document.uri.toString();
  clearTimeout(timers.get(key));
  timers.set(key, setTimeout(() => (timers.delete(key), check(document)), DEBOUNCE_MS));
}

/** Forget a closed document: cancel its timer and check, clear its diagnostics. */
function forget(document) {
  const key = document.uri.toString();
  clearTimeout(timers.get(key));
  timers.delete(key);
  const previous = running.get(key);
  if (previous) previous.child.kill();
  running.delete(key);
  collection.delete(document.uri);
}

function activate(context) {
  collection = vscode.languages.createDiagnosticCollection("skye");
  context.subscriptions.push(
    collection,
    vscode.workspace.onDidOpenTextDocument(check),
    vscode.workspace.onDidSaveTextDocument(check),
    vscode.workspace.onDidChangeTextDocument((event) => {
      if (isSkye(event.document) && settings(event.document).run === "onType") schedule(event.document);
    }),
    vscode.workspace.onDidCloseTextDocument(forget),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("skye")) vscode.workspace.textDocuments.forEach(check);
    }),
    vscode.languages.registerDocumentFormattingEditProvider("skye", { provideDocumentFormattingEdits: format }),
    vscode.commands.registerCommand("skye.check", () => {
      const editor = vscode.window.activeTextEditor;
      if (editor && isSkye(editor.document)) check(editor.document);
      else vscode.window.showInformationMessage("Skye: open a .skye file to check it.");
    })
  );
  vscode.workspace.textDocuments.forEach(check); // documents already open at activation
}

function deactivate() {
  for (const timer of timers.values()) clearTimeout(timer);
  for (const { child } of running.values()) child.kill();
  timers.clear();
  running.clear();
}

module.exports = { activate, deactivate };
