# Linux Mint po PR #59

Właściciel przekazał wynik audytu z 23 listopada 2026 r. Kanoniczny checkout `/home/l/projects/AIOA-spArkHAT` ma czystą gałąź `main` śledzącą `origin/main`. Zweryfikowano 2010 śledzonych plików, 98/98 testów offline na każdej wersji Python 3.11 i 3.12, source policy i One-Core. SHA to `914c9b1bf4dc7bf6ff14687d91560d9bcef1a5f6`, a drzewo `f4238a014e210e46863a4f6e7abadc40bf71fa61`. Cloud korzysta z przekazanego wyniku. Wskazany przez właściciela raport znajduje się na Linux Mint pod `/home/l/Desktop/AIOA_NONZERO_LOCAL_NIGHTLY_SYNC_RESULT_20261123.md`.

GitHub potwierdził cztery wymagane kontrole, One-Core, pochodzenie źródeł, MCP i domyślny CodeQL dla tego samego SHA. Wcześniejsza historia obejmuje #52–#59. [Core i packaging](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45107463038) · [CodeQL](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45107462144)

## Po kolejnym zaakceptowanym scaleniu

Przypnij SHA i drzewo **rzeczywistego merge commita z GitHuba** oraz wynik jego postmerge CI. Ustaw `AIOA_APPROVED_MAIN_SHA` i `AIOA_APPROVED_MAIN_TREE` z tego odbioru. Następnie w istniejącym checkoutcie operator uruchamia:

```sh
(
  set -eu
  cd /home/l/projects/AIOA-spArkHAT
  before=914c9b1bf4dc7bf6ff14687d91560d9bcef1a5f6
  case "$(git remote get-url origin)" in
    https://github.com/luciferprosun/AIOA-spArkHAT|https://github.com/luciferprosun/AIOA-spArkHAT.git|git@github.com:luciferprosun/AIOA-spArkHAT.git|ssh://git@github.com/luciferprosun/AIOA-spArkHAT.git) ;;
    *) exit 1 ;;
  esac
  test "$(git branch --show-current)" = main
  test "$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')" = origin/main
  test -z "$(git status --porcelain --untracked-files=all)"
  test "$(git rev-parse HEAD)" = "$before"
  git fetch origin
  test "$(git rev-parse refs/remotes/origin/main)" = "${AIOA_APPROVED_MAIN_SHA:?}"
  test "$(git rev-parse "$AIOA_APPROVED_MAIN_SHA^{tree}")" = "${AIOA_APPROVED_MAIN_TREE:?}"
  git merge-base --is-ancestor HEAD "$AIOA_APPROVED_MAIN_SHA"
  git diff --name-status "$before" "$AIOA_APPROVED_MAIN_SHA"
  git merge --ff-only "$AIOA_APPROVED_MAIN_SHA"
  test "$(git rev-parse HEAD)" = "$AIOA_APPROVED_MAIN_SHA"
  test "$(git rev-parse 'HEAD^{tree}')" = "$AIOA_APPROVED_MAIN_TREE"
  git status --short --branch
)
```

Jeżeli kontrola przerwie sekwencję, zachowaj checkout, lokalne commity i pliki. Przed ponowieniem porównaj aktualny HEAD, worktree i zatwierdzony zakres. Ewentualny rollback wykonaj przez zachowany worktree do porównania lub przez oddzielny autoryzowany PR z `git revert -m 1 <merge-sha>` i pełnym CI.

Użyj osobnych środowisk Python 3.11 i 3.12 z `.[nonzero]` i pakietami przypiętymi w `.github/workflows/nonzero-pr.yml`. Dla aktualnego kandydata regresja lokalna obejmuje GitHub WRITE, syntetyczne MCP READ, Native CAS i renderer:

```sh
PYTHONPATH=.:tests python -B -m unittest -v \
  test_github_remote_execution test_mcp_official_read_transcript \
  test_native_git_publication_boundary test_nz25_intent_cold_read \
  test_nz13_render_runtime
python -B tests/nz12_source_policy.py
python -B -m runtime.tools.nonzero_architecture --project-root .
python -m pip check
```

Jeśli zmieni się zakres PR, dobierz testy do faktycznych zmienionych modułów. Fizyczna kwalifikacja brokera stosuje przypięte binaria, biblioteki i profil hosta z hosted CI. Rozbieżność wymaga osobnego odbioru hosta. Zachowaj logi z SHA, wersją Pythona i zakresem. Testy LIVE mają osobne zgody.

Około 11,8 GiB historycznych katalogów opisano jako materiały do kwalifikacji. Ewentualne czyszczenie wymaga osobnego spisu worktree, unikalnych checkpointów, danych sesji i kopii oraz decyzji po końcowym odbiorze.
