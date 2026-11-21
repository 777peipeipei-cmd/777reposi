"""公式オープンデータ (www1.mbrace.or.jp) の競走成績 (K) と番組表 (B) を日ごとに取得する。

1リクエスト約2秒おき・順番に・キャッシュあり (途中から再開可)。ファイルが無い日は飛ばす。
usage: python download.py START(YYYY-MM-DD) END(YYYY-MM-DD) OUT_DIR
"""
import datetime
import os
import subprocess
import sys
import time


def main(start, end, out):
    os.makedirs(out, exist_ok=True)
    d = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    while d <= e:
        for kind in ('K', 'B'):
            name = f'{kind.lower()}{d:%y%m%d}.lzh'
            dst = os.path.join(out, name)
            miss = dst + '.missing'
            if os.path.exists(dst) or os.path.exists(miss):
                continue
            url = f'https://www1.mbrace.or.jp/od2/{kind}/{d:%Y%m}/{name}'
            r = subprocess.run(['curl', '-sS', '-m', '60', '-o', dst + '.part', '-w', '%{http_code}', url],
                               capture_output=True, text=True)
            code = r.stdout.strip()
            if code == '200' and os.path.getsize(dst + '.part') > 100:
                os.rename(dst + '.part', dst)
            else:
                if os.path.exists(dst + '.part'):
                    os.remove(dst + '.part')
                if code == '404':
                    open(miss, 'w').write(code)
                print('skip', name, code, flush=True)
            time.sleep(2)
        d += datetime.timedelta(days=1)
    print('download done', flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:4])
