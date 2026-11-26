; Uninstalling OrcaRouter Lite puts every connected coding agent back the way
; it was, so none is left pointed at an engine that no longer exists. The
; bundled engine is also the `orca` CLI; with the app closed it restores the
; agents' files directly. Tauri's updater runs the uninstaller with /UPDATE,
; and an update must not disconnect anyone.
;
; "Install command-line tool…" in the tray menu writes
; %USERPROFILE%\.orcarouter-lite\bin\orca.cmd and adds that folder to the
; user's PATH (HKCU\Environment). Uninstalling removes both; an update keeps
; them, since the shim points at the same orca-engine.exe.
!macro NSIS_HOOK_PREUNINSTALL
  ClearErrors
  ${GetOptions} $CMDLINE "/UPDATE" $R0
  ${If} ${Errors}
    DetailPrint "Restoring coding agents' original settings..."
    nsExec::ExecToLog '"$INSTDIR\orca-engine.exe" disconnect --all'
    Pop $R0

    DetailPrint "Removing the orca command..."
    Delete "$PROFILE\.orcarouter-lite\bin\orca.cmd"
    RMDir "$PROFILE\.orcarouter-lite\bin"
    ; Keep every other PATH entry, and the value's type (REG_EXPAND_SZ).
    nsExec::ExecToLog `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$d = Join-Path $$env:USERPROFILE '.orcarouter-lite\bin'; $$k = Get-Item 'HKCU:\Environment'; $$p = [string]$$k.GetValue('Path', '', 'DoNotExpandEnvironmentNames'); $$all = @($$p -split ';' | Where-Object { $$_ -ne '' }); $$keep = @($$all | Where-Object { [Environment]::ExpandEnvironmentVariables($$_).TrimEnd('\') -ne $$d }); if ($$keep.Count -ne $$all.Count) { Set-ItemProperty -Path 'HKCU:\Environment' -Name Path -Value ($$keep -join ';') -Type ExpandString }"`
    Pop $R0
    ; WM_SETTINGCHANGE "Environment" to every window, so new terminals see it.
    SendMessage 0xFFFF 0x1A 0 "STR:Environment" /TIMEOUT=5000
  ${EndIf}
!macroend
