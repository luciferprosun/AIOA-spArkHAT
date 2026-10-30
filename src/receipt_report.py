import sys
import json

def main():
    fail = pass_cnt = unknown = 0
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            print('INVALID_RECEIPT', file=sys.stderr)
            sys.exit(2)
        if not isinstance(obj, dict):
            print('INVALID_RECEIPT', file=sys.stderr)
            sys.exit(2)
        status = obj.get('status')
        if not isinstance(status, str):
            print('INVALID_RECEIPT', file=sys.stderr)
            sys.exit(2)
        if status == 'PASS':
            pass_cnt += 1
        elif status == 'FAIL':
            fail += 1
        elif status == 'UNKNOWN':
            unknown += 1
        else:
            print('INVALID_RECEIPT', file=sys.stderr)
            sys.exit(2)
    result = {'FAIL': fail, 'PASS': pass_cnt, 'UNKNOWN': unknown}
    print(json.dumps(result))

if __name__ == '__main__':
    main()