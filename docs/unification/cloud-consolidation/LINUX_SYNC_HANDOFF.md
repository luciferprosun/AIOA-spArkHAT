# Linux Mint po PR #61

Operator potwierdził kanoniczny checkout `/home/l/projects/AIOA-spArkHAT` na #59, commit `914c9b1bf4dc7bf6ff14687d91560d9bcef1a5f6`. Poniższy fast-forward obsługuje także checkout już zsynchronizowany do #60. GitHub potwierdził #61 jako merge commit z dokładnym drzewem. [PR #61](https://github.com/luciferprosun/AIOA-spArkHAT/pull/61)

Na scalonym main przeszły cztery wymagane kontrole, One-Core, pochodzenie źródeł, MCP Bridge i domyślny CodeQL. Na Pythonie 3.11 i 3.12 odnotowano po 4407 przypadków, w tym po pięć pominięć. Zweryfikowano po osiem bramek w obu archiwach. [Core](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45159158525) · [MCP](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45159158522) · [CodeQL](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45159158240)

W istniejącym checkoutcie operator uruchamia:

```sh
(
  set -eu
  cd /home/l/projects/AIOA-spArkHAT
  target=3b8e38df40ddd019075fc0053af3827ccb45c8bd
  target_tree=43664200f8f745b3f981c311c04744fb6b3c8106
  case "$(git remote get-url origin)" in
    https://github.com/luciferprosun/AIOA-spArkHAT|https://github.com/luciferprosun/AIOA-spArkHAT.git|git@github.com:luciferprosun/AIOA-spArkHAT.git|ssh://git@github.com/luciferprosun/AIOA-spArkHAT.git) ;;
    *) exit 1 ;;
  esac
  test "$(git branch --show-current)" = main
  test "$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')" = origin/main
  test -z "$(git status --porcelain --untracked-files=all)"
  before=$(git rev-parse HEAD)
  case "$before" in
    914c9b1bf4dc7bf6ff14687d91560d9bcef1a5f6) baseline_tree=f4238a014e210e46863a4f6e7abadc40bf71fa61 ;;
    e071c339942525e8bd8759adafb565c5ad412ce9) baseline_tree=f3f625a7f34f679638e0a3af3ebb395bb7fd9029 ;;
    "$target") baseline_tree="$target_tree" ;;
    *) exit 1 ;;
  esac
  test "$(git rev-parse 'HEAD^{tree}')" = "$baseline_tree"
  git fetch origin
  test "$(git rev-parse refs/remotes/origin/main)" = "$target"
  test "$(git rev-parse "$target^{tree}")" = "$target_tree"
  git merge-base --is-ancestor HEAD "$target"
  git diff --name-status "$before" "$target"
  git merge --ff-only "$target"
  test "$(git rev-parse HEAD)" = "$target"
  test "$(git rev-parse 'HEAD^{tree}')" = "$target_tree"
  git status --short --branch
)
```

Przy przerwaniu sekwencji zachowaj stan plików i lokalną historię. Ustal przyczynę rozbieżności przed ponowieniem. Rollback na GitHub wymaga osobnego autoryzowanego PR z `git revert -m 1 3b8e38df40ddd019075fc0053af3827ccb45c8bd`.

W środowiskach Pythona 3.11 i 3.12 z zależnościami `.[nonzero]` uruchom regresję zmienionych modułów. Przypadek fizycznej publikacji refu wymaga zgodnego Linux i systemu plików obsługującego mechanizm deskryptorowy.

```sh
PYTHONPATH=.:tests python -B -m unittest \
  test_github_remote_execution test_hybrid_repair test_nz13_dual_worker_repair \
  test_native_tools.NativeReadTests.test_github_transport_rejects_ambiguous_json_and_preserves_list_payloads \
  test_nz13_github_contexts test_nz26_mcp_public_license test_mcp_official_read_transcript \
  test_native_git_cold_controller test_native_git_publication_boundary test_nz25_intent_cold_read \
  test_nz13_render_runtime
python -B tests/nz12_source_policy.py
python -B -m runtime.tools.nonzero_architecture --project-root .
```

Zachowaj wyniki z dokładnym SHA i wersją Pythona. Native #69 nadal ma status `UNKNOWN / BLOCKED_SECURITY_REVIEW`. Cztery LIVE i wycofanie legacy są odrębnymi odbiorami.
