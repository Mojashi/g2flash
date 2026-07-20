# 公式FW のスクロール/入力の仕組みと使い方

Even G2(2.2.4.34)における「スクロール」が公式ファームでどう実装され、
BLE 経由でスマホ側から何がどの粒度で取れるかの調査メモ。
出所は末尾の [Sources](#sources)(g2-kit のソース＋ stock FW の逆アセンブル)。

## TL;DR

- **公式スクロールは `ListContainer` が実体**。カーソル移動・スクロール・ハイライトは
  **ファームがデバイス内で完結**して持つ。スマホは関与しない。
- **BT に流れてくるのは「タップ時の `list-click`(= 選択された `itemIndex`)」だけ**。
  ユーザーがスクロールしている最中の位置やデルタは **来ない**。
- ファーム内部には **符号付き int16 の (x,y) 連続値**が存在する(入力ディスパッチャの
  UI event `code 0x44`)が、**BT には出ない**。UI ウィジェットが内部で消費している。
- スムーズなピクセルスクロールを阻む壁は2つ:
  1. **BT 粒度** — 取れるのは item 単位・tap 駆動のイベントのみ。
  2. **両レンズの desync(限定的)** — `pager.ts` は List のアニメスクロールで左右が
     ずれ得ると指摘。ただし**公式FW自身が teleprompter 等でフル機能の smooth scroll を
     実装しており、`APP_PbTxEncodeScrollSync` で同期を取っている** → desync は
     「解ける」どころか既に解かれている。詳細は
     [公式は既に smooth scroll を持っている](#公式は既に-smooth-scroll-を持っている)。

## 公式は既に smooth scroll を持っている

stock FW の文字列調査で判明: **公式FW はフル機能の smooth scroll を実装済み**
(LVGL v9.3、IAR ビルド `s200_ap510b_iar_git`)。ビルドパスがそのままログ文字列に
残っており、関数名・ソースファイル・フィールド名が読める(＝完全 strip ではなく、
狙い撃ちRE がしやすい)。

- **Teleprompter**: `app/gui/teleprompt/`(`teleprompt_ui.c` / `_fsm.c` /
  `_timer_mgr.c` / `_page_data.c` / `teleprompt_file_list.c`)。auto-scroll タイマー
  (`Auto scroll timer start/stop`)、行単位スクロールバー
  (`[teleprompt.ui]scrollbar set: ... visible_lines=%d, scrollable_lines=%d`)、
  そして BLE 越しの **`APP_PbTxEncodeScrollSync`** = protobuf メッセージ
  **`Teleprompt_pb_scroll_sync`** の送信。つまり teleprompt のスクロールは
  **スマホと協調**していて、スクロール位置は BLE の pb メッセージで同期される
  (＝スクロールは firmware 内 LVGL で滑らかに描画しつつ、位置はスマホと coordinate)。
- **慣性 + アニメ + rubber-band(overscroll)**:
  - `SCROLLRELEASE_EVENT: ext_enable=%d, accumulated=%d, is_animating=%d`(accumulated=慣性量)
  - `Animation in progress (scroll:%d)` / `Animation complete: index=%d, scroll=%d, expected=%d`
  - `At top (scroll=%d), executing rubber band bounce effect` / `Bouncing in progress`
- **仮想化(cache)スクロール**: `ADD_UP/ADD_DOWN scroll with cache: old=%d, removed_h=%d,
  added_h=%d, new=%d` — 上下端で行をキャッシュ足し引きしながらスクロール(このメモで
  設計した「リング窓 + 端で継ぎ足し」が既に firmware に存在する)。
- **他画面も**: news/dashboard(`widget_news_detail_scroll_by`,
  `calendar_ext_scroll_by: from=%d to=%d, speed=%d`)。
- 土台は LVGL v9.3 の `lv_obj_scroll_by` / `lv_anim`(`lv_obj_scroll.c` / `lv_anim.c`)。

→ **smooth scroll 自体は hardware/firmware で成立済み**。`APP_PbTxEncodeScrollSync` の
存在から、両レンズ(または対スマホ)の同期も明示的に処理されている。残る作業は
「この既存エンジンを自前コンテンツに使えるか」であって、スクロール描画・同期・慣性を
一から作ることではない。

## 使い方(公式の範囲でできること)

`ListContainer` を作り、`onEvent` でタップを受ける。

```ts
import { G2Session, buildCreateStartUpPageContainer, buildUpdateListContainer } from "g2-kit/ble";
import { startHeartbeat } from "g2-kit/ui";

const ITEMS = ["apple", "banana", "carrot", "daikon", "exit"];
const session = await G2Session.open();

// CREATE は 280x130 でないと firmware が受けないので、REBUILD で全画面化する
await session.sendPb(0xe0, buildCreateStartUpPageContainer({ name: "menu", items: ITEMS, magic: 1 }).pb, 1);
const hb = startHeartbeat({ session, nextMagic: () => 2 });
await session.sendPb(0xe0, buildUpdateListContainer({ name: "menu", items: ITEMS, width: 576, height: 288, magic: 3 }).pb, 3);

// スクロールとハイライトはファームが自前でやる。スマホは「どの行がタップされたか」だけ受ける
session.onEvent((ev) => {
  if (ev.kind === "list-click" && ev.containerName === "menu") {
    console.log(`tapped row ${ev.itemIndex} = ${ITEMS[ev.itemIndex]}`);
  }
});
```

- 入力(こめかみタッチパッド / R1 リング)は **ファームがそのまま List のカーソル移動に使う**。
  スマホ側のコードは一切スクロールを動かさない。
- スマホが知れるのは **タップした瞬間の選択 index** だけ。

### ページングパターン(g2-kit `ui/pager.ts`)

「スクロールを追跡できない」+「アニメスクロールはレンズ desync で不快」への公式的な回避策:
List に **`▲ Prev page` / `▼ Next page` のナビ行を自分で差し込み**、その行へのタップを
ページ送りに map する(`buildPagerView` / `pagerResolveTap`)。**瞬間ページ切り替え**なので
アニメの desync 窓を踏まない。連続スクロールの体験は諦める代わりに、安定・快適を取る設計。

## BT に載るもの / 載らないもの

`session.onEvent()`(sid=0xe0 flag=0x01 の非同期イベント channel)で受かるもの:

| イベント | 内容 | スクロール用途 |
|---|---|---|
| `list-click` | `itemIndex` / `CurrentSelectItemIndex`(選択された行) | ○ tap 時のみ・item 単位 |
| `text-click` | text container のクリック | – |
| `sys-event` | `eventType`(OsEventTypeList)+ `eventSource`(2=ring, 1/3=glasses R/L) | △ 離散の種別のみ |
| `private-event` | container 固有 eventId/eventData | アプリ依存 |
| `SCROLL_TOP` / `SCROLL_BOTTOM` | 端に到達 | △ **実タップ時しか確実に飛ばない**(ユーザースクロール中は不可) |
| 生スクロールデルタ (x,y) | — | ✗ **BT に出ない**(内部 `code 0x44` に留まる) |
| IMU (x,y,z) | proto 上は `Sys_ItemEvent.IMUData` | ✗ 定義はあるが **実機で populate されたのを観測できていない** |

→ **BT の入力粒度は「item 単位・tap 駆動」。あなたの直感どおり荒い。**

## ファーム内部の実像(逆アセンブル)

`ghidra_addr = file_off + 0x39E680`(既知パッチ3サイトで検証済み)。

- 入力ディスパッチャ **`FUN_004424a2`**。入力レコードの構造:
  ```
  byte0    = source (0/1=こめかみL/R, 4=R1リング)
  byte2-5  = subtype (u32)  — 0..0x10 の離散ジェスチャコード
  byte6-9  = data (u32)     — ジェスチャ毎のペイロード
  ```
- **`subtype 4/5` は `data` を符号付き int16 ×2 (x,y) として `sxth` デコード**し、
  UI event **`code 0x44`** として `FUN_0045fc80(ctx, 0x44, &{x,y})` で post する。
  → **細かい連続座標/デルタは firmware 内部には確かに存在する。**
- しかし UI/BT 層には **coarse な種別しか出ない**。`gesture_fwd.c` が示すとおり、
  EvenHub の UI ハンドラは一部の code(例: ring release の `0x4a`)を **drop** する。
  `code 0x44` も同様にアプリ/BT へは surface されていないと見られる(要 static 確認)。

つまり **「量子化して落としている」のではなく「細かいイベントを UI 消費側が拾っていない」**。
データは内部にあるのに外へ出ていない、という構図。

## 公式を超えたい場合(CFW)

- **細かい入力を取る**: `code 0x44`(int16 x,y)を `gesture_fwd.c` と同じフック点
  (`FUN_004424a2` / `FUN_0045fc80`)で横取りし、連続 y デルタとして SysEvent 転送 or
  オンデバイスのスクロール状態に直結 → 1:1 指追従が可能。**touch.bin の書き換えは不要**
  (座標は既に main app まで届いている)。
- **残る最大リスク = レンズ desync**: 上記の「アニメスクロールは左右がずれて不快」は
  ハード起因。CFW の**両眼同期 present**(`zlib_glue.c` の snapshot/deferred: 両レンズで
  worker を走らせる仕組み)が、この desync をどこまで潰せるかが smooth scroll 実現の要。
  ここは**実機検証必須**(そもそも公式が smooth scroll を避けている核心理由がこれ)。

## Sources

- g2-kit(`demos/node_modules/g2-kit`):
  - `ble/events.ts` — 非同期イベントの decode(list-click / sys-event / private-event)
  - `ble/ring.ts` L394-400 — 「ring tap/scroll は glasses 経由で sys-event としてスマホへ」
  - `ui/pager.ts` L1-18 — 「firmware がカーソル/スクロールを持つ」「SCROLL_TOP/BOTTOM は
    タップ時のみ」「両レンズ desync で animated scroll は不快」
  - `examples/list-taps.ts` — `session.onEvent()` → `list-click` の受信例
- stock FW `g2_2.2.4.34.bin` の逆アセンブル:
  - `FUN_004424a2`(入力ディスパッチャ、subtype 4/5 → int16 x,y → UI code 0x44)
  - `patches/gesture_fwd.c`(フック点・EVT_SRC・SysEvent 送出 `FUN_004ff232`)
