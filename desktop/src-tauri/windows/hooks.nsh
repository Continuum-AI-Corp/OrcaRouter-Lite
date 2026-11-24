; Uninstalling OrcaRouter Lite puts every connected coding agent back the way
; it was, so none is left pointed at an engine that no longer exists. The
; bundled engine is also the `orca` CLI; with the app closed it restores the
; agents' files directly. Tauri's updater runs the uninstaller with /UPDATE,
; and an update must not disconnect anyone.
!macro NSIS_HOOK_PREUNINSTALL
  ClearErrors
  ${GetOptions} $CMDLINE "/UPDATE" $R0
  ${If} ${Errors}
    DetailPrint "Restoring coding agents' original settings..."
    nsExec::ExecToLog '"$INSTDIR\orca-engine.exe" disconnect --all'
    Pop $R0
  ${EndIf}
!macroend
