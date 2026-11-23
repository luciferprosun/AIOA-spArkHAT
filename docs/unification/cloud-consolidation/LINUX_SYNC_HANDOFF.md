# Linux Mint po PR #63

Operator potwierdził kanoniczny checkout `/home/l/projects/AIOA-spArkHAT` na #59, commit `914c9b1bf4dc7bf6ff14687d91560d9bcef1a5f6`. Poniższy fast-forward obsługuje także checkout już zsynchronizowany do #60, #61 lub #62. GitHub potwierdził #63 jako merge commit z dokładnym drzewem. [PR #63](https://github.com/luciferprosun/AIOA-spArkHAT/pull/63)

Plan dotyczy wyłącznie `main` o SHA `8bd2fe14033f1b49609092a353cd7e6fd6b8d3ef` i drzewie `56709b77f066df0567a9f3c4bdbd8182dd6bc38e`. Operator sprawdza aktualny stan wymaganych kontroli przed synchronizacją. Merge obejmuje #51–#63. Ostatnie zmienione moduły to `codex_worker.py`, `coding_tasks.py`, `git_publish.py`, `intent.py` i `render_runtime.py`. Pełny wykaz znajduje się w `PR63_CHANGED_PATHS.txt`. [Core CI](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45223650707) · [MCP](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45223705533) · [CodeQL](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45223650071)

W istniejącym checkoutcie operator uruchamia:

```sh
(
  set -eu
  cd /home/l/projects/AIOA-spArkHAT
  target=8bd2fe14033f1b49609092a353cd7e6fd6b8d3ef
  target_tree=56709b77f066df0567a9f3c4bdbd8182dd6bc38e
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
    3b8e38df40ddd019075fc0053af3827ccb45c8bd) baseline_tree=43664200f8f745b3f981c311c04744fb6b3c8106 ;;
    f2179eb0e6bb4bfd1c5d53ff4353eeb22fb1a78c) baseline_tree=f4155563badd40d647896747ad6daedfe861a5d0 ;;
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

Przy przerwaniu sekwencji zachowaj stan plików i lokalną historię. Ustal przyczynę rozbieżności przed ponowieniem. Rollback na GitHub wymaga osobnego autoryzowanego PR z `git revert -m 1 8bd2fe14033f1b49609092a353cd7e6fd6b8d3ef`.

W środowiskach Pythona 3.11 i 3.12 z zależnościami `.[nonzero]` uruchom regresję zmienionych modułów. Przypadek fizycznej publikacji refu wymaga zgodnego Linux i systemu plików obsługującego mechanizm deskryptorowy.

```sh
PYTHONPATH=.:tests python -B -m unittest \
  test_nz13_native_coding_lifecycle test_native_git_cold_controller \
  test_native_git_publication_boundary test_core_intent test_nz11_codex_transport \
  test_nz13_render_runtime test_nz13_worker_messages test_mcp_official_read_transcript
python -B tests/nz12_source_policy.py
python -B -m runtime.tools.nonzero_architecture --project-root .
```

Zachowaj wyniki z dokładnym SHA i wersją Pythona. Native #69 nadal ma status `UNKNOWN / BLOCKED_SECURITY_REVIEW`. Cztery LIVE i wycofanie legacy są odrębnymi odbiorami.
