# approach-trainer — master TODO

Status as of 2026-06-13. Pending work is at the top; completed work is at the bottom.

---

## TODO (open)

### Pipeline / data completeness
- [ ] **Verify factory backlog finished** — 1,528 new videos (Douyin Mandarin + nstv/sergio/shorts English) running through `factory.py` (batched 5× scribe → compile-down → segment). Confirm new `clips` rows + `segments` written; re-run `factory.py` to mop up any stragglers (downloads still arriving).
- [ ] **Transcribe EVERYTHING** (no translation, ever — user confirmed). All clips/courses get in-language machine transcription. Non-English stays in its own language. The remaining gap is just coverage (YT/Douyin backlog + non-mp4 below), not translation.
- [ ] **Douyin full catalogs** — only 3 creators pulled (`jianzhong-qinggan`, `jianzhong-shejiao`, `ostrichbro`); anonymous API caps ~23 posts. Need logged-in Douyin cookie or TikHub paid API for full catalogs.
- [ ] **More channels** — finish/queue remaining English + intl (FR/ES/DE/Mandarin) creators per `docs/creators.md` and `yt_lang_dl.sh`. Currently downloaded: nstv (shorts+videos), sergio-sorokin, + IG set.
- [ ] **Quality audit** — confirm clips are ≤1080p-or-best-available (re-grab any low-res); courses are torrent-sourced so capped as-is. *(Spot-check: IG/YT sample is mostly 1920-tall / 1080p; sergio-sorokin sampled at 720p — verify and re-grab if a better source exists.)*
- [x] **Case-sensitivity bug fixed** — it was NOT exotic formats; all course video is `.mp4`/`.MP4`. The `*.mp4` glob missed **55 uppercase `.MP4`** files (TenGame 35, Transformation Mastery 19, …). Fixed `factory.py` + `transcribe_longform.py` to case-insensitive (`837` vs old `782`). The 55 get ingested on the next factory run.
- [ ] **Transcribe the 55 newly-visible `.MP4` course files** — re-run factory/transcribe over `pickup-courses` after the current backlog finishes; they'll flow through normally now.

### Storage / locations
- [ ] **Media is on a spinning HDD — but there's no SSD with room.** `/mnt/media` = `/dev/sdc1` Seagate Portable, **HDD (ROTA=1)**, 4.5T, **76% full (1.1T free)**. The NVMe SSD (Lexar 2TB) has only **~60G free** → can't hold the media. The only roomy target is `/dev/sdb2` (20T Expansion, **13T free**) — still a spinning HDD. **Decision needed:** (a) accept HDD (fine for sequential video reads/transcode), or (b) move to the 20T HDD for headroom (more space, not faster). A small SSD working-dir for `factory-audio`/`course-audio` scratch could help throughput. Update path roots in `scripts/factory.py` + download scripts if anything moves.

### Platform / data model
- [~] **Outcome taxonomy → meta+sub+detail — IMPLEMENTED, migration queued.** New scheme live in `segment.py`+`factory.py`: `commitment{contact,date,physical,pull} / engagement{rapport,unresolved} / rejection{soft,hard,non_responsive}` + a free-text **`outcome_detail`** (e.g. "boyfriend", "number+IG") for queryable reasons. Validated (detail populates correctly). segments table gets `outcome_meta/sub/detail` cols. **OPEN:** run `retag_outcomes.py` (deterministic legacy→new backfill) once the factory finishes writing; the 53 legacy `close` rows are flagged `detail='review'` for manual re-tag; `outcome_detail` for old rows fills via future re-segmentation/enrichment.
- [ ] **Diarized, compile-down SRT export** — generate `.srt` (diarized, from our turns w/ start-end) for courses + clips. User expected SRTs to exist for the courses; they don't. Tie this into the non-mp4 ingest below (those especially need SRTs).
- [ ] **Finalize platform direction** — keep the parent/segment offset model (virtual slicing, browse-by-outcome) we built; **drop the "pause-before-approach" drill fields** (user deprecated them). Write/refresh the PRD (only `docs/creators.md` exists now).

### Research
- [~] **RSD Julien controversy clip — RESEARCHED (year was 2014, not 2011).** Julien Blanc. The viral footage = his YouTube video **"White male… in Tokyo"** (posted **8 Sep 2014**): grabbing women's heads/throats (#ChokingGirlsAroundTheWorld), pushing heads toward crotch, "in Tokyo if you're a white male you can do what you want," + the **#HowToMakeHerStay** abuse-wheel slide. Blew up Nov 2014 via **#TakeDownJulienBlanc**; CNN/Chris Cuomo interview **17 Nov 2014**; visa bans (Australia, UK, etc.). Source = his Tokyo **seminar/bootcamp infield footage** posted to YouTube + tie-ins to the **Pimp** program.
  - **Not in our library** (deleted Nov 2014 before our archive grab). **DOWNLOADED** 4 mirrors → `pickup-courses/RSD Julien - Controversy/` (Dailymotion `x2a668q` + 3 YouTube reuploads). They ingest on the next factory pass. *(Note: these are reuploads/compilations, not guaranteed the pristine original — review once transcribed.)*

### superwhisper-api (shared package) — API improvements
- [x] **Supported-langs on the model spec + cruft deleted — DONE.** `AudioModelSpec.supported_languages` (ISO-639-3 frozenset) + `.supports("Mandarin"/"zh"/"zho")`; distilled into `audio/_language_support_data.py`; **deleted** `language_support.json` + `.md`; gitignored the transient probe matrix; kept `language_probe.py` + 102 fixtures + new `generate-support-data` phase to re-distill after probing a new model. Verified: only `scribe-v2` does Tajik; Deepgram rejects it.
- [x] **OCR benchmark — DONE** — `ocr_probe.py` + committed `tests/fixtures/ocr/` (30 IAM handwriting lines), CER-scored across the vision GPT models. **Result: gpt-5.3-chat-latest best (CER 0.029) but 4.5× slower; gpt-5.2 best value (0.031 @ 0.86s); 5.4-nano worst (0.154, avoid for OCR).** Reusable harness for future vision models.
- [ ] **OCR compile-down** — *now* worth building: a multi-model OCR consensus (5.3-chat + 5.2 + 5.4-mini agree) mirroring text `compile_down`. Benchmark shows the top 3 are close + complementary.
- [ ] **Recheck Serbian (`sr_rs`) + Somali (`so_so`)** — scored under threshold on every model; likely a script-mismatch/similarity artifact (Serbian Latin vs Cyrillic), not true non-support.
- [ ] **Marketing vs probed** — Scribe nailed 100/102 FLEURS; if its published list has languages beyond FLEURS's 102, pull extra fixtures from another dataset and probe those too.
- [ ] **OCR compile-down** — build a multi-model OCR consensus pass (GPT-family only for vision) mirroring the text `compile_down`.
- [ ] **Model-selection metrics** — capture per-model speed + capability signals (like Superwhisper's speed/"smart" axes) to inform automatic model choice per task.
- [ ] **Image enablement audit** — confirm vision/image support added in the recent update is actually being used in the OCR flows (chat-history question).
- [ ] **Benchmark check** — is GPT 5.3-full smarter than 5.4-mini/nano per current benchmarks? Note the answer for model defaults.
- [ ] **Meta: refactor the API** — we've repeated compile-down and OCR motions across projects; consider consolidating these patterns into the package.

---

## DONE

### Transcription & enrichment (approach-trainer SQLite `data/clips.db`)
- [x] **782/782 long-form `sources` transcribed** — diarized 5× Scribe → compile-down consensus → SQLite (courses: Project GO, Tyler, Tate, Todd, Hot Seat; + RSD Julien YouTube archive & Transformation Mastery & Pimp).
- [x] **Scene-cut detection (ffmpeg) on everything** — `sources` 782/782 and `clips` 6,323/6,323 have `cuts` stored.
- [x] **Durations backfilled** — 782/782 sources via ffprobe.
- [x] **Segmentation (cut-aware, virtual slicing)** — `sources` → 2,768 segments / 782 parents; `clips` → 8,363 segments / 6,322 parents. Interactions tagged with outcomes (number/rejection/instant_date/pull/kiss/etc.) for browse-by-result.

### Factory pipeline
- [x] **`factory.py` built** — per-item + batched: scan media roots → detect cuts → extract audio → 5× scribe (per-language, `--max-workers 200`) → compile-down consensus → segment → write rows. Resumable/idempotent.
- [x] **Download triggers wired** — `factory_trigger.sh` appended to the pure-download scripts (serialized on a shared lock).

### superwhisper-api
- [x] **Canonical language reference** — `superwhisper_api/languages.py` (100 ISO-639-3 langs from ElevenLabs Scribe docs; `scribe_code()/language_name()/script_of()/resolve()` accept name/639-1/639-3/alias; `cmn`→error, `zho` correct).
- [x] **Empirically-probed support matrix** — `language_probe.py` pulls 1 FLEURS clip per language (102 fixtures committed), probes every model with code-fallback, scores vs ground truth → `language_support.json` + `language_support.md`. Result: scribe-v2 100/102, s1-voice 83, ultra 68, nova-2 34, nova-3 20.

### Tooling / hygiene
- [x] **uv-enforcement PreToolUse hook** — bare `python`/`pip` blocked at the harness; `uv run` required.
- [x] **Codex gpt-5.5 review** of `scripts/` — ruff/ty/shellcheck clean.
