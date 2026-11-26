# Jedna tabela decyzji dla 23 kontraktów zewnętrznych

## Odczyt poprzedzający PR #76

Źródło Core to `d2fc4cb88c1777e572c099c8082b93e6b7a6c0b1`. Dostępne dane nie potwierdzają aktywnego odbiorcy żadnego z 23 wierszy. Każdy wiersz zachowuje `UNKNOWN_EXTERNAL` i indywidualny warunek z tabeli poniżej.

Przed zmianą danego kontraktu wymagany jest reprezentatywny klient, dokładny import lub endpoint, wspierana wersja i zanonimizowana próbka. Przed formalnym wycofaniem potrzeba decyzji właściciela, zakresu, czasu i powiadomienia. Sama dalsza integracja ograniczonej funkcji Core, bez zmiany kontraktu, nie zależy od zgody na wycofanie całego legacy. #24 wymaga odrębnego porównania tras, trybu i frameworka, a #57 odróżnia Render YAML od efektu Git. [Checkpoint](CHECKPOINT.json) · [Macierz 69](PARITY69_UPDATED.csv)

Zakres potwierdzonych aktywnych odbiorców zewnętrznych pozostaje pusty. GitHub i historia widzą dawne wdrożenie Render oraz historyczne interfejsy. Kategoria w tabeli to rekomendowany tryb rozliczenia, a każdy wiersz zachowuje `UNKNOWN_EXTERNAL` do przypięcia odbiorcy lub decyzji właściciela o zakresie.

| ID | Rekomendowana grupa | Decyzja i konkretny warunek |
| --- | --- | --- |
| 11 | Core obsługuje rolę | Odebrać związanie owner approval, kapsuły, nonce i sesji przez Core. Zachować dawne decyzje jako dowody. |
| 12 | Core obsługuje rolę | Porównać podpisaną kapsułę i binding base, task, PatchSet, etap. Historyczny format kapsuły przyjąć tylko jako obojętną projekcję. |
| 13 | Adapter przy potwierdzonym odbiorcy | Ustalić wersję i wymagane pola DTO repo i poświadczenia. Adapter odrzuca sekrety i nie tworzy autoryzacji. |
| 20 | Adapter przy potwierdzonym odbiorcy | Zmapować VERIFIED, DENIED i UNKNOWN do odczytu ze wskazaniem źródła i rodzaju dowodu. |
| 24 | Adapter przy potwierdzonym odbiorcy | Przypiąć stare HTTP route, headers, status i semantykę trybu. Przy braku odbiorcy wycofać alias i stary transport w uzgodnionym oknie. |
| 26 | Adapter przy potwierdzonym odbiorcy | Porównać timeline, kolejność, ograniczenia długości, redakcję i taint. |
| 30 | Core obsługuje rolę | Odebrać odczyt trwałego klucza oraz odmowę cross-run i replay na próbce rzeczywistego odbiorcy. |
| 33 | Adapter przy potwierdzonym odbiorcy | Porównać DTO ADD/MODIFY/DELETE, bajty i wiązania task, run i worker. |
| 34 | Core obsługuje rolę | Porównać evaluate i recheck, sprawdzić drift, digest, ograniczenia ścieżki i odmowę sekretów. |
| 40 | Adapter przy potwierdzonym odbiorcy | Odebrać kolejność, statusy PASS, FAIL, STOP i UNKNOWN, czytelność wcześniejszego podpisu i odmowę powtórzenia. |
| 44 | Kandydat do formalnego wycofania | Ustalić, czy odbiorca wymaga historycznego lifecycle Docker. Dopuszczalne zachowania kwalifikować przez zamknięty profil Core. |
| 46 | Kandydat do formalnego wycofania | Ustalić konkretną wymaganą receptę i odebrać efekt i sprzątanie w istniejącym brokerze. |
| 47 | Kandydat do formalnego wycofania | Porównać lock i artefakty Python/Node. Historyczny setup i rejestry rozliczać osobno po potwierdzeniu odbiorcy. |
| 50 | Core obsługuje rolę | Zachować wyzwanie właściciela. Przypiąć wymaganie Strands interrupt przed zgodą na adapter. |
| 52 | Adapter przy potwierdzonym odbiorcy | Projektować wyłącznie wymagane zanonimizowane pola DTO. Wyłączyć nonce i uprawnienie apply z projekcji. |
| 55 | Adapter przy potwierdzonym odbiorcy | Porównać artifact ref, rozmiar, digest, taint i trace, chroniąc prywatne ścieżki. |
| 56 | Core obsługuje rolę | Odebrać bytes, hash i allowlist z odmową symlink, hardlink i driftu. |
| 57 | Nadal nierozstrzygnięte | Ustalić, czy rzeczywisty odbiorca wymaga zapisu Render YAML czy efektu Git. Każdy efekt kwalifikuje się osobno. |
| 60 | Core obsługuje rolę | Odebrać ograniczenie deskryptorem, odmowę zmiany inode i limity. |
| 61 | Core obsługuje rolę | Związać artefakty i dozwolone operacje z ograniczonym profilem, sprawdzić brak rozszerzenia uprawnień. |
| 62 | Adapter przy potwierdzonym odbiorcy | Odebrać obojętną propozycję Render z digestami before/after i historycznym dowodem. |
| 66 | Core obsługuje rolę | Odebrać niezależny reopen root, path, bytes, runtime i odmowę po wykryciu zmiany. |
| 67 | Adapter przy potwierdzonym odbiorcy | Porównać report, receipt i proof origin z zachowaniem podpisu, UNKNOWN i zakazu automatycznego apply. |

Dla potwierdzonego kontraktu zapisać właściciela, dokładny punkt wejścia, wspieraną wersję, przykładowy poprawny i błędny fixture oraz dowody odczytu. Dla formalnego wycofania zapisać zakres, termin, powiadomienie i decyzję właściciela. [Macierz 69](PARITY69_UPDATED.csv)

## Klasyfikacja decyzji

W kolumnie `external_contract_disposition` wszystkie 23 wpisy mają `UNKNOWN`. Dziewięć ról ma odpowiednik Core, dziesięć może wymagać adaptera po potwierdzeniu odbiorcy, trzy są kandydatami do wycofania, a #57 ma nierozstrzygnięty wymagany efekt. Żaden kontrakt zewnętrzny nie uzyskał dowodu `VERIFIED`, `IMPLEMENTATION_REQUIRED` ani `NOT_APPLICABLE_WITH_EVIDENCE`.

## Odczyt dowodów C05 dla #30, #33 i #40

| ID | Potwierdzony zakres Core | Brakujący dowód kontraktu |
| --- | --- | --- |
| #30 | Fixed vectors Judge i W7A, identyczne pokwitowanie po restarcie, zero drugiej mutacji i odmowa klucza innego przebiegu. Testy `test_nonzero_parity` oraz `test_nz13_cloudops_contracts`. | Aktualny klient, dokładny import lub endpoint, wersja i zapisany rzeczywisty rekord wraz ze skrótami. |
| #33 | Wyprowadzenie ADD, MODIFY i DELETE z plików. Odtworzenie tej samej projekcji Core oraz odmowa podmienionego zagnieżdżonego PatchSet. Testy `test_hybrid_patchset` i `test_nz25_coding_receipt_read`. | Próbka komunikatu konsumenta. W7A wiąże osobne UUID, trace i run, a Core wiąże task, session i źródło. |
| #40 | Kolejność porażka, naprawa, PASS, zachowanie UNKNOWN przy problemie sprzątania i niezmienny odczyt po wznowieniu. Testy `test_hybrid_repair` i `test_nz25_coding_receipt_read`. | Próbka historycznego DTO wraz z identyfikatorem sandboxa, skrótami stdout/stderr i regułami pochodzenia lub podpisu etapu. |

Wszystkie trzy wpisy zachowują `UNKNOWN_EXTERNAL`. Pozytywne wyniki odczytano w obu przebiegach Pythona na dokładnym `main` `8bd2fe14033f1b49609092a353cd7e6fd6b8d3ef`. [CI po #63](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45223650707/attempts/2)


## Przegląd odbiorców po #76, 26 listopada 2026

Badany Core `d2870f33bb740184f7c2a18a7ea8f90b070fbd64`. Dla każdego z 23 modułów odtworzono rzeczywisty import wraz z importami względnymi z 377 plików Python na W7A `392487849eddc7444f5159994b66b72e73f15934`. Poniżej podano moduł wewnętrzny w `src/aioa_cloudops_agent/` oraz przykładowy importowany symbol. Wiersze z `__init__` wskazują rzeczywisty reeksport pakietu. Zestaw wszystkich znalezionych importerów w prywatnym dowodzie ma SHA-256 `7333bcf5fa21439e17f4469ed63215e3cb058ca3af093a896232b2c0a1b7d445`. [Źródło W7A](https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent/tree/392487849eddc7444f5159994b66b72e73f15934/src/aioa_cloudops_agent)

| ID | Ścieżka kontraktu | Historyczny importer | Przykładowy symbol |
|---|---|---|---|
| 11 | `execution/authority.py` | `execution/__init__.py` | `ExecutionAuthorityDenied` |
| 12 | `execution/capsule.py` | `execution/__init__.py` | `ExecutionCapsuleBuildRequest` |
| 13 | `execution/contracts.py` | `execution/authority.py` | `ExecutionApprovalDecision` |
| 20 | `github/write_contracts.py` | `github/effect_repository.py` | `GitEffectOwnership` |
| 24 | `local_api/contracts.py` | `local_api/application.py` | `LOCAL_API_BODY_MAX_BYTES` |
| 26 | `local_api/views.py` | `local_api/application.py` | `run_view` |
| 30 | `nz/contracts.py` | `agent/coding_worker.py` | `NonZeroContract` |
| 33 | `patchset/contracts.py` | `patchset/policy.py` | `FileContentIdentity` |
| 34 | `patchset/policy.py` | `patchset/__init__.py` | `BoundedPatchSetPolicy` |
| 40 | `repair_loop/contracts.py` | `repair_loop/coordinator.py` | `RepairAttemptReceipt` |
| 44 | `sandbox/contracts.py` | `sandbox/provider.py` | `CleanupReceipt` |
| 46 | `sandbox/provider.py` | `sandbox/__init__.py` | `DockerAvailability` |
| 47 | `sandbox/setup.py` | `sandbox/provider.py` | `DeterministicSetupPlanner` |
| 50 | `workspace/authority.py` | `workspace/authority_agent.py` | `WorkspaceAuthorityDenied` |
| 52 | `workspace/authority_contracts.py` | `workspace/authority.py` | `WorkspaceApprovalDecisionRecord` |
| 55 | `workspace/contracts.py` | `execution/authority.py` | `canonical_workspace_json_digest` |
| 56 | `workspace/evidence.py` | `workspace/agent.py` | `WorkspaceEvidenceService` |
| 57 | `workspace/executor.py` | `workspace/authority_agent.py` | `WorkspaceAtomicPatchExecutor` |
| 60 | `workspace/jail.py` | `workspace/evidence.py` | `WorkspaceJail` |
| 61 | `workspace/profile.py` | `workspace/agent.py` | `WORKSPACE_REMEDIATION_PROFILE_ID` |
| 62 | `workspace/proposal.py` | `workspace/tools.py` | `WorkspacePatchProposalBuilder` |
| 66 | `workspace/verification_boundary.py` | `workspace/verifier.py` | `IndependentWorkspaceObservation` |
| 67 | `workspace/verification_contracts.py` | `workspace/authority_repository.py` | `WorkspaceRecoveryClassification` |

Przeszukano indeks GitHub Code Search dla właściciela z wyrażeniem `aioa_cloudops_agent` (16 plików, wszystkie w AIOA-spArkHAT, głównie mapy/testy i dwa strażniki) oraz indeks globalny dla dokładnego tokenu i domeny demo. W trzech lokalnych projektach Connect Lite, Companion i META znalazły się wyłącznie strażniki architektury w META. Nie ustalono obecnego niezależnego odbiorcy ani jego wersji. Indeks publiczny ma niepełne pokrycie. Prywatne integracje, jury i bezpośrednie wywołania HTTP pozostają po stronie właścicieli usług.

Dla #24/#26 ostatni skuteczny deployment Render wskazuje inny commit od W7A: `03d1c8f6a1d254c98c0b4e88fc93e25ea85ed4c7`. Jego skrypt startowy wywołuje `python -m aioa_cloudops_agent.portable_server`, a w źródle `GET /health` odpowiada statusem 200 i obiektem `{"mode":"mock","service":"aioa-local-hitl","status":"ok"}`. Blueprint wskazuje `/ready` jako health check. Dla #18 istnieje historyczne `repository_service.py` z `git push --porcelain` i docelowym `refs/heads/…`; żaden bieżący klient nie potwierdził wymogu Git HTTPS. Te dane identyfikują reprezentatywne kontrakty źródłowe. Do odbioru dzisiejszej zależności potrzeba właściciela klienta, przypiętej wersji oraz próbki korzystającej z tego wejścia. [Render blueprint](https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent/blob/03d1c8f6a1d254c98c0b4e88fc93e25ea85ed4c7/render.yaml) · [Rzeczywiste trasy](https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent/blob/03d1c8f6a1d254c98c0b4e88fc93e25ea85ed4c7/src/aioa_cloudops_agent/local_api/application.py#L239-L254) · [Git w W7A](https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent/blob/392487849eddc7444f5159994b66b72e73f15934/src/aioa_cloudops_agent/github/repository_service.py#L659-L676)

Rekomendacja dla 23 ID: zachować ich osobne `UNKNOWN_EXTERNAL` i wstrzymać deprecjację. Właściciel konkretnego interfejsu może rozliczyć grupę ID jednym rekordem wyłącznie wtedy, gdy odnoszą się do tego samego potwierdzonego klienta i zakresu. Minimalny zapis decyzji do podpisania po uzupełnieniu:

```json
{"ids":[],"decision":"KEEP_COMPATIBILITY | RETIRE_AFTER_NOTICE","client_owner":null,"client_and_version":null,"import_or_http_route":null,"redacted_positive_and_negative_sample_digests":[],"retirement_scope":null,"notice_channel_and_date":null,"effective_utc":null,"owner_attestation_ref":null}
```

`KEEP_COMPATIBILITY` kieruje do porównania z istniejącą funkcją Core; dla `RETIRE_AFTER_NOTICE` konieczne są potwierdzony zakres i skutki, termin oraz powiadomienie. Wpis pozostaje otwarty przy braku decyzji. W szczególności przed wycofaniem #57 trzeba rozstrzygnąć, czy klient wymaga zmiany YAML Render, czy publikacji Git.

W trakcie przygotowań A–D ustalono konkretne cele prób technicznych. Dotyczą odrębnych wierszy PARTIAL #2, #3, #17, #18, #19, #41 i #63. Dla 23 pozycji tego rejestru nadal potrzeba identyfikacji obecnego klienta, wersji i reprezentatywnego wejścia albo zatwierdzonego zakresu deprecjacji. Potwierdzenie GitHub, że docelowe Actions są włączone, blokuje próbę C. O tym, czy wymagany jest Git HTTPS dla #18, decyduje odbiorca tego kontraktu. [Odbiory wykonawcze](NONZERO_RETIREMENT_GATE.md) · [Dokładne piny](LIVE_QUALIFICATION.json)

**Odczyt 26 listopada 2026, godz. 18:31 UTC.** Scalenie #77 zamknęło integrację wyłączonego zakresu RH-07. Klient i wersja dla każdego z 23 wierszy pozostają niepotwierdzone. Aktualne kroki właściciela wraz z odrębnym pozwoleniem dla naprawy #41, odczytem Render i przywróceniem z drugiego trwałego miejsca opisuje pakiet decyzji. [Pakiet decyzji](NONZERO_RETIREMENT_GATE.md) · [Macierz 69](PARITY69_UPDATED.csv)
