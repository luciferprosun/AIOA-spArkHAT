# G1 — BLOCKED_STORAGE_TOOLCHAIN

**Nie zakwalifikowano dysku do instalacji. Jawne zapisy danych toolchainu:0;
brak katalogu `AIOA_ANDROID_TOOLCHAIN`, stagingu, write probe i dużych pobrań.**

Read-only metadata zgadza się z oczekiwaniem: `/media/l/LSC_DATA3`, `/dev/sda1`,
UUID `1c748500-8e12-4e23-80be-115ce7f3937a`, ext4, rw/nosuid/nodev,
bez ro/noexec i bez symlink w sprawdzonym łańcuchu. Mountpoint jest właściciela
i writable.154024210432 bajty wolne na HDD wystarczają na rezerwę25GiB po
planowanym maksymalnym12GiB; system root ma ponad10GiB.

`/sys/fs/ext4/sda1/errors_count` i warning_count wynoszą0; odczyt dziennika
ostatnich48h nie znalazł pasujących błędów. Te sygnały **nie zamykają historii
USB/ext4/I/O**. SMART nie jest dostępny (`smartctl` brak), sysfs model daje
„Generic”, więc nie udowodniono aktualnej kondycji/identyfikacji fizycznego WD.
Znaleziony raport odzyskiwania z22.08.2026 dotyczy przede wszystkim repozytoriów
i testów; nie jest aktualną niezależną kwalifikacją tego nośnika.
Nie znaleziono dostępnego autorytatywnego bieżącego reportu WD Watch/Core,
który wiąże to urządzenie/mount generation, rozstrzyga wcześniejsze usterki
oraz aktualne SMART/USB. Nie wykonywano fsck, sudo, SMART instalacji,
remount, naprawy, restartu obserwatora ani zmian zadań odzyskiwania.

Z tego powodu G2 jest **BLOCKED_G1**. Nie wykonano nawet16KiB write/read/hash/fsync:
prompt wymaga najpierw niezależnego dowodu. Samo rw,0recenterrors albo nowy folder
testowy nie są zastępczą kwalifikacją. Odczyty mogą podlegać zwykłemu atime systemu;
0 oznacza brak jawnych zapisów instalatora, nie pomiar fizycznych zapisów kontrolera.

## Jak skrypty zachowują bramkę

Doctor obserwuje kernel/mount/free-space i zwraca BLOCKED przy niepewności.
Instalator nie ma `--force`, `--unsafe`, `--qualification-pass` ani fixture CLI.
Nie tworzy dowodu PASS, trust pin ani licencji. Kontrakt interop
`aioa.storage.independent-qualification.v1` w skryptach jest **nowym wymaganym
adapterem do niezależnego wydawcy**, nie twierdzeniem o istniejącym API WD Watch.
Na tym hoście wydawca/binding pozostaje niedostępny.

Ewentualne późniejsze podłączenie wymaga niezależnego review autentycznego
źródła kwalifikacji; prywatny native operator pin wiąże dokładny digest i ścieżkę
raportu na zdrowym systemowym dysku, a każda operacja ponawia kontrolę UUID,
mount_id, expiry, SMART/USB/prior_faults i rezerw. Nie wolno ręcznie wpisywać PASS
do JSON ani przypinać raportu modelu, by ominąć brak rzeczywistej kwalifikacji.
Rekordy są czytane z jednego FD i hashują te same bajty, które są parsowane.
Bez udowodnionego binding skrypty mają pozostać BLOCKED.

Po rzeczywistym spełnieniu read-only admission dopiero ograniczony probe może
utworzyć własne staging16KiB, fsync pliku/katalogu i sprawdzić hash/tożsamość.
EIO/mismatch zatrzymuje etap i zachowuje diagnostykę. Sukces dotyczy tylko
tego ograniczonego profilu w danym momencie, nie wieczystej certyfikacji HDD.

PDF zawiera dosłownie niezdefiniowane `ZZTOK0ZZ`; potwierdzono na renderze.
Nie przypisano mu wymyślonego znaczenia — decyzja jest wyrażona jawnie powyżej.
