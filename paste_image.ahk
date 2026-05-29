; Obsidian Paste Image - AHK v2 Hotkey Trigger
; ------------------------------------------------------------------
; Hotkey: Win+Shift+V
;
; Strategy for determining the active file to save images next to:
;
;   1. PRIMARY — Active editor window title (Antigravity / VS Code pattern)
;      Title format (Antigravity):
;        "<filename.md> - <workspace> - Antigravity IDE"
;        "<filename.md> - <workspace> (Workspace) - Antigravity IDE"
;      Title format (VS Code):
;        "<filename.md> — Visual Studio Code"
;        "<filename.md> (Working Tree) — Visual Studio Code"
;
;      If a full absolute path is embedded in the title, it is passed via
;      --active-file for a direct, zero-scan lookup.
;      If only a filename is found, it is passed via --title so the Python
;      script can scan the vault for it.
;
;   2. SECONDARY — Workspace name from the title is passed via --workspace,
;      allowing the script to derive the vault project from the ZID prefix.
;
;   3. FALLBACK — When neither can be determined the script falls back to
;      the default_project value defined in config.ini.
;
; Installation:
;   • Requires AutoHotkey v2.0+
;   • Requires Python to be on PATH and Pillow/pyperclip installed
;   • Script path and Python path are configurable below
; ------------------------------------------------------------------

#Requires AutoHotkey v2.0

; ---- CONFIGURATION -----------------------------------------------
; Adjust these two paths to match your installation.
SCRIPT_DIR  := "U:\voothi\20260529201233-obsidian-paste-image"
PYTHON_EXE  := "python"
CONFIG_FILE := SCRIPT_DIR . "\config.ini"
; ------------------------------------------------------------------

#HotIf WinActive("ahk_class Chrome_WidgetWin_1") || WinActive("ahk_exe antigravity.exe") || WinActive("ahk_exe Code.exe") || WinActive("ahk_exe obsidian.exe") || WinActive("ahk_class CabinetWClass")
; Register on all common editor and file-manager windows.
; Remove the #HotIf block entirely to make it global.
#HotIf

; =================== HOTKEY =======================================
; Win + Shift + V — Paste clipboard image into vault
#HotIf
^+v:: PasteImageToVault()   ; Ctrl+Shift+V  (change as desired)
; or use:
; #v:: PasteImageToVault()  ; Win+V

PasteImageToVault() {
    global SCRIPT_DIR, PYTHON_EXE, CONFIG_FILE

    ; --- 1. Get active window title ----------------------------------
    title := WinGetTitle("A")

    ; --- 2. Try to extract a full absolute path from the title -------
    ;  Some terminals / file managers show full paths like:
    ;    "U:\voothi.vault\kardenwort-mpv\conversations\note.md"
    activeFile := ""
    if RegExMatch(title, "([A-Za-z]:\\[^\x00-\x1F""*<>?|]+\.md)", &m)
        activeFile := m[1]

    ; --- 3. Try to extract just the markdown filename ----------------
    mdFilename := ""
    if (activeFile = "") {
        if RegExMatch(title, "([\w-]+\.md)\b", &m2)
            mdFilename := m2[1]
    }

    ; --- 4. Try to extract workspace token from the title -----------
    ;  Antigravity format: "... - 20260308110646-kardenwort-mpv (Workspace) - ..."
    ;  VS Code format:     "... — <workspace folder> — ..."
    workspace := ""
    if RegExMatch(title, "(\d{14}-[\w-]+)\s*(?:\(Workspace\))?", &mw)
        workspace := mw[1]

    ; --- 5. Build the Python command ---------------------------------
    srcScript := SCRIPT_DIR . "\src\paste_image.py"
    cmd := PYTHON_EXE . " """ . srcScript . """"
    cmd .= " --config """ . CONFIG_FILE . """"

    if (activeFile != "") {
        cmd .= " --active-file """ . activeFile . """"
    } else if (mdFilename != "") {
        cmd .= " --title """ . mdFilename . """"
    }

    if (workspace != "")
        cmd .= " --workspace """ . workspace . """"

    ; --- 6. Run the script, capture output ---------------------------
    result := RunWaitGetOutput(cmd, SCRIPT_DIR)

    ; --- 7. Report status --------------------------------------------
    ;  The Wikilink is written back to clipboard by the Python script.
    ;  Show a brief tooltip so the user knows it succeeded.
    if InStr(result, "![[") {
        ; Extract the wikilink from the output
        if RegExMatch(result, "!\[\[([^\]]+)\]\]", &ml)
            ToolTip("✓ Pasted: ![[" . ml[1] . "]]")
        else
            ToolTip("✓ Image pasted to vault")
    } else {
        ; Something went wrong — show an abbreviated error balloon
        errLine := ""
        for line in StrSplit(result, "`n") {
            if InStr(line, "[!]") {
                errLine := Trim(line)
                break
            }
        }
        ToolTip("✗ Paste failed`n" . (errLine != "" ? errLine : "Check console for details"))
    }

    ; Auto-dismiss tooltip after 3 seconds
    SetTimer(() => ToolTip(), -3000)
}

; =================== HELPERS ======================================

; Run a command, wait for it to finish, and return its stdout output.
RunWaitGetOutput(cmd, workDir := "") {
    tempFile := A_Temp . "\paste_image_out_" . A_TickCount . ".txt"
    fullCmd  := 'cmd /c ' . cmd . ' > "' . tempFile . '" 2>&1'

    if (workDir != "")
        Run(fullCmd, workDir, "Hide Wait")
    else
        Run(fullCmd, , "Hide Wait")

    output := ""
    if FileExist(tempFile) {
        output := FileRead(tempFile, "UTF-8")
        FileDelete(tempFile)
    }
    return output
}
