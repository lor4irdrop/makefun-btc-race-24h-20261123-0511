# cbBTC core-plus-dip bot — make.fun btc-race

Bot trading paper-money cbBTC untuk [make.fun](https://make.fun) btc-race.
Simulasi murni: modal $1.000 paper money, tanpa uang beneran. Hadiah race
$200 total, top 10 dibayar berdasarkan net PnL race window (race 24 jam
terbaru: 1st $100, 2nd $27, 3rd $15, 4th $13, 5th $10, 6th–10th $7).

> Status, dicek 12 Nov 2026 00:25 UTC (07:25 WIB): race 24 jam terbaru
> (`btc-race-24h-20261111-0801`, deadline 11 Nov 12:01 UTC) **sudah tutup
> dan sedang racing live** — tidak bisa dimasuki. Belum ada race btc-race
> baru yang open di `GET /api/competitions` saat cek itu (hanya 3 race
> btc lama, semua sudah tutup deadline-nya). Bot ini disiapkan untuk
> **race berikutnya**.

## Strategi

Core-plus-dip, terinspirasi (bukan copy) dari pemenang race 4 jam
(@joe, $50: "70% core long plus SMA4 dip sleeve"):

- **Core (50%):** beli sekali di bar pertama, hold sampai akhir window.
  Ini taruhan bahwa BTC drift naik sementara bot reversion murni duduk
  di cash.
- **Dip sleeve (~50%):** beli saat close >= 30 bps di bawah SMA(4),
  keluar di +60 bps, -120 bps, atau setelah 240 bar. Satu posisi dip
  dalam satu waktu, cooldown 10 bar setelah exit (tiap round trip
  biayanya ~6 bps: fee 4 bps + slippage 2 bps).
- **Guards (tambahan dari bot ini):** tidak beli dip saat close > 3%
  di bawah SMA(120) atau > 200 bps di bawah SMA(4) dalam satu langkah
  (flush, bukan dip); tidak ada dip baru saat drawdown > 18%; keluar
  dari dip saat drawdown > 20%. Race memberi peringkat di bawah semua
  yang memenuhi syarat kalau max drawdown > 25%.

Semua hitungan harga memakai integer (Python `int`) di atas harga
integer harness, tanpa floating point, tanpa jam, tanpa random, tanpa
network, tanpa file. Dua run di data yang sama menghasilkan reply
yang identik byte demi byte.

## Protokol (bars-replay/v1)

`main.py` membaca JSON lines dari stdin dan menjawab satu JSON reply
per batch di stdout. Format exact, dari schema `agent-fun/bars-replay/v1`:

- `hello`: `{type:"hello", protocol:"agent-fun/bars-replay/v1", seed,
  symbols:[{symbol, mint, price_scale, qty_scale}],
  capital:{quote:"USDC", quote_scale, quote_units}, bar_interval:"1m",
  caps:{max_open_positions, max_orders_per_bar, max_weight_bps,
  shorts:false, leverage:false},
  fees:{fee_bps, slippage_bps, min_notional_quote_units}, latency_bars:1}`
- `batch`: `{type:"batch", seq, t, bars:[{symbol, t, o, h, l, c,
  v, o_depth:[...], c_depth:[...]}], fills:[{client_id, symbol, side,
  status:"filled"|"rejected", reason, decided_bar, fill_bar, price,
  qty, notional_quote_units, fee_quote_units}],
  account:{cash_quote_units, positions:[{symbol, qty,
  cost_quote_units}], equity_quote_units}}`
  Bar: harga di `price_scale` simbol, volume di `qty_scale` (atau
  null); depth dalam USDC raw units per hop.
- `done`: `{type:"done", seq, reason, account}`.
- Reply: `{"type":"reply", "seq": N, "orders": [...]}` dengan order
  buy `{side:"buy", client_id, symbol, notional_quote_units:"<u64>",
  max_slippage_bps}` atau sell `{side:"sell", client_id, symbol,
  qty:"<u64>", max_slippage_bps}`. Hanya key itu yang boleh ada.
- Order yang diputuskan di bar k terisi di open bar k+1 (fee 4 bps +
  slippage 2 bps + price impact constant-product terhadap pool depth).
  Hasil penjualan tidak bisa mendanai pembelian di reply yang sama.
  Order di bar terakhir ditolak; semua posisi di-flatten di close
  terakhir.

## Run lokal

```sh
python3 main.py < input.jsonl > replies.jsonl
```

`main.py` hanya memakai standard library Python (json, sys,
collections) dan jalan di Python 3.13 seperti yang diminta make.fun
(diuji di Python 3.12 di sini; tidak ada fitur spesifik 3.13).

## Backtest lokal

`backtest.py` **bukan** bagian submission — alat lokal saja. Ia
menjalankan `main.py` asli sebagai subprocess dan mereplay bar 1 menit
persis seperti harness: fill di open menit berikutnya, fee 4 bps +
slippage 2 bps. Price impact pool **tidak** dimodelkan (data pengganti
tidak punya pool depth) — lihat `backtest_results.md`.

```sh
python3 backtest.py data/dev_window_synth.jsonl --twice
```

Data di `data/` adalah **sintetis** (generator deterministik di
`data/generate_data.py`, seed tetap), BUKAN data dev resmi make.fun.
Data dev resmi ada di kit race (`GET /c/<slug>/kit`), yang gagal
diunduh dalam sesi ini dan tidak dicoba ulang. Sebelum submit ke race
berikutnya, bot **wajib** di-grade ulang dengan kit resmi
(`node cli/makefun.mjs grade-local --kit . --bot <dir> --driver process`).

## Cara submit (manual, oleh Ndan — belum dilakukan)

1. Tunggu race btc-race berikutnya buka di https://make.fun
   (`GET /api/competitions?status=open`).
2. Download kit race itu, jalankan `grade-local` pada bot ini dengan
   data dev resmi. Lolos hanya jika dev PnL bersih > $0.
3. Buat repo GitHub **publik** baru dari akun GitHub Ndan, dibuat
   **setelah** kompetisi dibuka, berisi `main.py` + `LICENSE` (MIT) +
   README ini di root. Jangan sertakan `backtest.py` / `data/`
   (itu alat lokal; submission yang bersih hanya butuh `main.py`).
4. Submit repo + commit SHA + bundle transcript sesi coding-agent
   via kit CLI (`node cli/makefun.mjs bundle` lalu `submit`), sesuai
   `skill.md` di https://make.fun/skill.md. Maks 10 submission total.
5. Akun make.fun butuh wallet Solana terhubung untuk menerima hadiah.
   Yang dibutuhkan hanya **alamat publik** Solana Ndan — jangan
   pernah kirim / tampilkan private key atau seed phrase ke siapa pun,
   termasuk ke Muse.

## Yang belum ada / belum terverifikasi

- Race berikutnya belum buka (cek terakhir 12 Nov 2026 00:25 UTC / 07:25 WIB).
- Data dev window resmi race berikutnya belum didapat (kit gagal
  diunduh); semua angka backtest di repo ini memakai data sintetis.
- Akun GitHub Ndan (lor4irdrop) dan alamat publik Solana untuk payout
  sudah diberikan dan terverifikasi 11 Nov 2026 — tersimpan di Muse,
  bukan di repo submission.
- Tidak ada janji penghasilan: ini kompetisi, bukan gaji. Race 24 jam
  terbaru diikuti 345 submission untuk 10 tempat berbayar.
