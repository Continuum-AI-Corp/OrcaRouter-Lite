# Launch checklist

Timed to the first signed release (roadmap V1 → V8). Post everything on the same day the release goes live.

## Before the day

- [ ] **Signed release.** Apple Developer ID + notarization secrets, the `desktop-release` environment with the eSigner secrets and the
      updater key are set (RELEASING.md §4, §7, §8); a `v0.x` tag has produced `.dmg` (Apple silicon and
      Intel), `-setup.exe`, `.deb`/`.AppImage`, `latest.json` and `orcarouter-lite.rb`.
- [ ] Open each installer on a clean machine: no Gatekeeper or SmartScreen warning, setup opens, an agent connects.
- [ ] **Homebrew.** `Continuum-AI-Corp/homebrew-tap` exists; the release's cask is in `Casks/orcarouter-lite.rb`
      and the CLI formula in `Formula/orcarouter-lite.rb`; `brew install --cask continuum-ai-corp/tap/orcarouter-lite`
      and `brew install continuum-ai-corp/tap/orcarouter-lite` both work.
- [ ] **winget.** The release's three manifests (`packaging/winget/README.md`) are submitted to
      `microsoft/winget-pkgs` and merged; `winget install OrcaRouter.Lite` works. The first merge can take days:
      submit as soon as the release exists.
- [ ] **PyPI.** `pipx install orcarouter-lite` gives a working `orca`.
- [ ] **Landing page** (V1, V6): Settings → Pages → Source: GitHub Actions; the `pages` workflow is green;
      <https://continuum-ai-corp.github.io/OrcaRouter-Lite/> shows the right download for macOS, Windows and Linux,
      the other-OS links, the brew/winget commands and the 19-agent logo strip, in light and dark, on a phone.
- [ ] The download button links straight to the installer once the release exists (it falls back to the
      release page until then).
- [ ] **README**: badge and "Works with" strip render on GitHub; INSTALL.md's "before the first release" note
      is removed now that releases exist.
- [ ] **Demo GIF** re-recorded against the release build (`scripts/record_demo.sh`); numbers still marked as demo data.
- [ ] **Savings card** (V2) screenshot for the Product Hunt gallery, if V2 has shipped.
- [ ] Copy check: OrcaRouter is described as a hosted gateway with free models to start, never as a credit
      offer (`tests/unit/test_no_free_credit_claims.py` guards this); own keys always work.

## On the day

- [ ] Morning (US Pacific): publish the GitHub release notes.
- [ ] Show HN post ([show-hn.md](show-hn.md)); stay in the thread for the first hours and answer every question.
- [ ] Product Hunt page ([product-hunt.md](product-hunt.md)) with the GIF and the savings card.
- [ ] Listing pull requests for Claude Code, OpenCode and Goose ([../listings/](../listings/)), then the rest over the week.
- [ ] Awesome-list entries ([../listings/awesome-lists.md](../listings/awesome-lists.md)).

## After

- [ ] Triage issues daily for the first week; diagnostics from "Copy diagnostics" go straight into issues.
- [ ] Track installs by source: release download counts per asset, landing-page links carry `ref=lite-*`
      tags (no cookies, no user identifier).
- [ ] Follow-up post after a week: what people asked for, what shipped.
