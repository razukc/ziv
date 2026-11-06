/*
 * test_band.c — host unit tests for firmware/band: the decoder, the queue
 * (with the file store), the turn's compiled timelines against expectations
 * hand-derived from haptic_timing.h for both profiles, the beat mode, the
 * controls, and the transport protocol against an in-memory scripted frame
 * adapter (frame shapes, order, nack reasons, backoff, resume).
 *
 * Every expected number below is written as arithmetic on the generated
 * constants — never a literal millisecond — so a spec change moves the
 * expectations with the tables.
 *
 * Build & run:  python3 firmware/band/run_band_tests.py
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "drv2605.h"
#include "haptic_out.h"
#include "mock_drv2605.h"
#include "queue.h"
#include "queue_file_host.h"
#include "transport.h"
#include "turn.h"
#include "utterance.h"

static int failures = 0;
static int checks = 0;

#define CHECK(cond, msg) do { \
    checks++; \
    if (!(cond)) { failures++; printf("FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); } \
} while (0)

#define CHECK_EQ(a, b, msg) do { \
    long long got_ = (long long) (a), want_ = (long long) (b); \
    checks++; \
    if (got_ != want_) { failures++; printf("FAIL: %s (got %lld, want %lld) (%s:%d)\n", msg, got_, want_, __FILE__, __LINE__); } \
} while (0)

#define CHECK_STR(a, b, msg) do { \
    const char *ga_ = (a), *wb_ = (b); \
    checks++; \
    if (ga_ == NULL || wb_ == NULL || strcmp(ga_, wb_) != 0) { failures++; printf("FAIL: %s (got '%s', want '%s') (%s:%d)\n", msg, ga_ ? ga_ : "(null)", wb_ ? wb_ : "(null)", __FILE__, __LINE__); } \
} while (0)

/* ---- fixtures ------------------------------------------------------------- */

static const char *k_two_words =
    "{\"v\":1,\"id\":\"golden-message-two-words\",\"wearer\":\"w_1\",\"kind\":\"message\","
    "\"from\":{\"sender\":\"mira\",\"label\":\"Mira\"},\"prefix\":{\"mark\":\"ziv\",\"tail\":\"double-tap\"},"
    "\"words\":[\"taxi\",\"here\"],\"spec_version\":4}";

static const char *k_hello_word =
    "{\"v\":1,\"id\":\"golden-message-one-word\",\"wearer\":\"w_1\",\"kind\":\"message\","
    "\"from\":{\"sender\":\"mira\"},\"prefix\":{\"mark\":\"ziv\",\"tail\":\"message\"},"
    "\"words\":[\"hello\"],\"spec_version\":4}";

static const char *k_pending =
    "{\"v\":1,\"id\":\"golden-pending-rem\",\"wearer\":\"w_1\",\"kind\":\"reminder\","
    "\"from\":{\"sender\":\"agent\",\"label\":\"pills\"},\"words\":[],\"body_pending\":true,\"spec_version\":4}";

static const char *k_reply =
    "{\"v\":1,\"id\":\"golden-reply-no-prefix\",\"wearer\":\"w_1\",\"kind\":\"message\","
    "\"from\":{\"sender\":\"agent\"},\"words\":[\"yes\"],\"source\":\"live\",\"spec_version\":4}";

/* A spec_version other than the header's — built at run time so the test
 * stays true whatever the current version is. */
static void with_spec(char *buf, size_t cap, const char *id, int spec)
{
    snprintf(buf, cap, "{\"id\":\"%s\",\"wearer\":\"w_1\",\"kind\":\"message\",\"from\":{\"sender\":\"s\"},"
             "\"words\":[\"ok\"],\"spec_version\":%d}", id, spec);
}

static int letter(char c) { return c - 'a'; }
static uint32_t cell(char c) { return haptic_cell_ms(c); }

/* Recorded beats from the turn's beat callback. */
typedef struct { uint32_t at, buzz; uint8_t mask; char label[16]; } rec_beat;
typedef struct { rec_beat b[256]; int n; } rec_beats;
typedef struct { turn_phase phase; int wi; char label[40]; } rec_event;
typedef struct { rec_event e[64]; int n; } rec_events;

static void rec_on_beat(void *ctx, uint32_t now, const haptic_out_step_t *st, const char *label)
{
    rec_beats *r = (rec_beats *) ctx;
    if (r->n >= 256) { return; }
    r->b[r->n].at = now;
    r->b[r->n].buzz = st->buzz_ms;
    r->b[r->n].mask = st->dot_mask;
    snprintf(r->b[r->n].label, sizeof r->b[r->n].label, "%s", label);
    r->n++;
}

static void rec_on_event(void *ctx, turn_phase phase, int wi, const char *label)
{
    rec_events *r = (rec_events *) ctx;
    if (r->n >= 64) { return; }
    r->e[r->n].phase = phase;
    r->e[r->n].wi = wi;
    snprintf(r->e[r->n].label, sizeof r->e[r->n].label, "%s", label);
    r->n++;
}

typedef struct {
    mock_drv mock; drv2605_bus bus; haptic_out h; turn t; rec_beats beats; rec_events events;
} rig;

static void rig_init(rig *r, turn_profile p, uint32_t pace)
{
    mock_init(&r->mock);
    mock_bus(&r->bus, &r->mock);
    haptic_out_init(&r->h, &r->bus);
    turn_init(&r->t, &r->h, p, pace);
    r->beats.n = 0;
    r->events.n = 0;
    turn_set_callbacks(&r->t, rec_on_event, &r->events, rec_on_beat, &r->beats);
}

/* Walk the turn on a virtual clock until idle; returns the final clock. */
static uint32_t walk(turn *t, uint32_t now)
{
    for (int guard = 0; guard < 100000; guard++) {
        uint32_t next = turn_step(t, now);
        if (next == 0) { return now; }
        if (next > now) { now = next; }
    }
    return now;
}

static void expect_beat(const rec_beats *r, int i, uint32_t at, uint8_t mask, uint32_t buzz, const char *label)
{
    char m[96];
    if (i >= r->n) { snprintf(m, sizeof m, "beat %d exists", i); CHECK(false, m); return; }
    snprintf(m, sizeof m, "beat %d (%s) start", i, label); CHECK_EQ(r->b[i].at, at, m);
    snprintf(m, sizeof m, "beat %d (%s) mask", i, label); CHECK_EQ(r->b[i].mask, mask, m);
    snprintf(m, sizeof m, "beat %d (%s) buzz", i, label); CHECK_EQ(r->b[i].buzz, buzz, m);
    snprintf(m, sizeof m, "beat %d label", i); CHECK_STR(r->b[i].label, label, m);
}

/* ---- the decoder ------------------------------------------------------------ */

static void test_decoder(void)
{
    ziv_utterance u;
    CHECK_EQ(utterance_decode_json(k_two_words, strlen(k_two_words), &u), ZIV_UTT_OK, "two words decode");
    CHECK_STR(u.id, "golden-message-two-words", "id");
    CHECK_EQ(u.kind, HAPTIC_KIND_MESSAGE, "kind message");
    CHECK(u.has_prefix, "has prefix");
    CHECK_EQ(u.mark_len, 3, "mark ziv has 3 letters");
    CHECK_EQ(u.mark[0], letter('z'), "mark z"); CHECK_EQ(u.mark[1], letter('i'), "mark i"); CHECK_EQ(u.mark[2], letter('v'), "mark v");
    CHECK_EQ(u.tail, HAPTIC_KIND_TAIL_TABLE[HAPTIC_KIND_MESSAGE], "tail is the kind's");
    CHECK_EQ(u.word_count, 2, "two words");
    char w[ZIV_UTT_WORD_MAX + 1];
    CHECK_EQ(utterance_word_text(&u, 0, w, sizeof w), 4, "taxi has 4 letters"); CHECK_STR(w, "taxi", "word 0");
    CHECK_EQ(utterance_word_text(&u, 1, w, sizeof w), 4, "here has 4 letters"); CHECK_STR(w, "here", "word 1");
    CHECK_EQ(utterance_word_text(&u, 2, w, sizeof w), 0, "word 2 does not exist");
    CHECK(!u.body_pending, "not pending");
    CHECK_EQ(u.spec_version, HAPTIC_SPEC_VERSION, "spec version");
    CHECK_EQ(u.source, ZIV_SOURCE_SENDER, "default source sender");

    CHECK_EQ(utterance_decode_json(k_hello_word, strlen(k_hello_word), &u), ZIV_UTT_OK, "prefix.tail as kind name accepted");
    CHECK_EQ(utterance_decode_json(k_pending, strlen(k_pending), &u), ZIV_UTT_OK, "pending decodes");
    CHECK(u.body_pending && u.word_count == 0 && !u.has_prefix, "pending: no words, no prefix");
    CHECK_EQ(u.kind, HAPTIC_KIND_REMINDER, "kind reminder");
    CHECK_EQ(utterance_decode_json(k_reply, strlen(k_reply), &u), ZIV_UTT_OK, "reply decodes");
    CHECK_EQ(u.source, ZIV_SOURCE_LIVE, "source live");

    /* distinct errors, never a truncation */
    char buf[1024];
    with_spec(buf, sizeof buf, "spec-mismatch-1", HAPTIC_SPEC_VERSION + 1);
    CHECK_EQ(utterance_decode_json(buf, strlen(buf), &u), ZIV_UTT_ERR_SPEC_VERSION, "spec mismatch is its own error");
    CHECK_EQ(u.word_count, 0, "nothing partial survives a refusal");

    const char *bad_kind = "{\"id\":\"kind-unknown-1\",\"kind\":\"alarm\",\"words\":[\"ok\"],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(bad_kind, strlen(bad_kind), &u), ZIV_UTT_ERR_KIND, "unknown kind");

    const char *bad_letters = "{\"id\":\"letters-bad-1\",\"kind\":\"message\",\"words\":[\"Taxi\"],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(bad_letters, strlen(bad_letters), &u), ZIV_UTT_ERR_LETTERS, "uppercase letter refused");
    const char *digit = "{\"id\":\"letters-bad-2\",\"kind\":\"message\",\"words\":[\"a1\"],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(digit, strlen(digit), &u), ZIV_UTT_ERR_LETTERS, "digit refused");
    const char *empty_word = "{\"id\":\"letters-bad-3\",\"kind\":\"message\",\"words\":[\"\"],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(empty_word, strlen(empty_word), &u), ZIV_UTT_ERR_LETTERS, "empty word refused");

    /* 33 letters: over the cap, not cut to 32 */
    char long_word[2048];
    snprintf(long_word, sizeof long_word, "{\"id\":\"over-cap-word\",\"kind\":\"message\",\"words\":[\"%s\"],\"spec_version\":4}",
             "abcdefghijklmnopqrstuvwxyzabcdefg");
    CHECK_EQ(utterance_decode_json(long_word, strlen(long_word), &u), ZIV_UTT_ERR_OVER_CAP, "33-letter word is over cap");
    snprintf(long_word, sizeof long_word, "{\"id\":\"at-cap-word\",\"kind\":\"message\",\"words\":[\"%s\"],\"spec_version\":4}",
             "abcdefghijklmnopqrstuvwxyzabcdef");
    CHECK_EQ(utterance_decode_json(long_word, strlen(long_word), &u), ZIV_UTT_OK, "32-letter word accepted");
    CHECK_EQ(u.word_len[0], 32, "all 32 letters kept");

    /* 65 words: over the cap */
    {
        char many[4096];
        size_t off = (size_t) snprintf(many, sizeof many, "{\"id\":\"over-cap-words\",\"kind\":\"message\",\"words\":[");
        for (int i = 0; i < ZIV_UTT_WORDS_MAX + 1; i++) {
            off += (size_t) snprintf(many + off, sizeof many - off, "%s\"a\"", i ? "," : "");
        }
        snprintf(many + off, sizeof many - off, "],\"spec_version\":4}");
        CHECK_EQ(utterance_decode_json(many, strlen(many), &u), ZIV_UTT_ERR_OVER_CAP, "65 words is over cap");
    }
    const char *long_mark = "{\"id\":\"over-cap-mark\",\"kind\":\"message\",\"prefix\":{\"mark\":\"abcdefghi\",\"tail\":\"double-tap\"},\"words\":[\"ok\"],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(long_mark, strlen(long_mark), &u), ZIV_UTT_ERR_OVER_CAP, "9-letter mark is over cap");

    const char *bad_tail = "{\"id\":\"tail-disagrees\",\"kind\":\"message\",\"prefix\":{\"mark\":\"ziv\",\"tail\":\"triple-pulse\"},\"words\":[\"ok\"],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(bad_tail, strlen(bad_tail), &u), ZIV_UTT_ERR_TAIL, "tail disagreeing with the kind refused");

    const char *bad_id = "{\"id\":\"short\",\"kind\":\"message\",\"words\":[\"ok\"],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(bad_id, strlen(bad_id), &u), ZIV_UTT_ERR_ID, "7-char id refused");
    const char *bad_id2 = "{\"id\":\"has space!\",\"kind\":\"message\",\"words\":[\"ok\"],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(bad_id2, strlen(bad_id2), &u), ZIV_UTT_ERR_ID, "id with bad chars refused");

    const char *empty = "{\"id\":\"empty-no-pending\",\"kind\":\"message\",\"words\":[],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(empty, strlen(empty), &u), ZIV_UTT_ERR_EMPTY, "no words and not pending refused");
    const char *bad_src = "{\"id\":\"source-bad-1\",\"kind\":\"message\",\"words\":[\"ok\"],\"source\":\"magic\",\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(bad_src, strlen(bad_src), &u), ZIV_UTT_ERR_SOURCE, "unknown source refused");
    const char *bad_v = "{\"v\":2,\"id\":\"wire-version-2\",\"kind\":\"message\",\"words\":[\"ok\"],\"spec_version\":4}";
    CHECK_EQ(utterance_decode_json(bad_v, strlen(bad_v), &u), ZIV_UTT_ERR_WIRE_VERSION, "wire v2 refused");
    const char *no_spec = "{\"id\":\"missing-spec-1\",\"kind\":\"message\",\"words\":[\"ok\"]}";
    CHECK_EQ(utterance_decode_json(no_spec, strlen(no_spec), &u), ZIV_UTT_ERR_FIELD, "missing spec_version");
    CHECK_EQ(utterance_decode_json("not json", 8, &u), ZIV_UTT_ERR_JSON, "not JSON");
    CHECK_EQ(utterance_decode_json("[1,2]", 5, &u), ZIV_UTT_ERR_JSON, "not an object");

    /* words set by hand (the body hand-off) */
    CHECK_EQ(utterance_decode_json(k_pending, strlen(k_pending), &u), ZIV_UTT_OK, "pending again");
    const char *ws[2] = { "meds", "nine" };
    CHECK_EQ(utterance_set_words(&u, ws, 2), ZIV_UTT_OK, "set words");
    CHECK_EQ(u.word_count, 2, "two words set");
    CHECK_EQ(utterance_word_text(&u, 1, w, sizeof w), 4, "nine"); CHECK_STR(w, "nine", "word 1 nine");
    const char *bad_ws[1] = { "N1" };
    CHECK_EQ(utterance_set_words(&u, bad_ws, 1), ZIV_UTT_ERR_LETTERS, "bad body letters refused");
    CHECK_EQ(u.word_count, 2, "a refused body leaves the words as they were");

    /* names */
    CHECK_STR(utterance_kind_name(HAPTIC_KIND_SYSTEM), "system", "kind name");
    CHECK_EQ(utterance_kind_from_name("error"), HAPTIC_KIND_ERROR, "kind from name");
    CHECK_STR(utterance_pattern_id(HAPTIC_PAT_END_OF_MESSAGE), "end-of-message", "pattern id");
    CHECK_STR(utterance_err_name(ZIV_UTT_ERR_OVER_CAP), "over_cap", "error name");
}

/* ---- the queue --------------------------------------------------------------- */

static void make_utt(ziv_utterance *u, const char *id, const char *word)
{
    char buf[512];
    snprintf(buf, sizeof buf, "{\"id\":\"%s\",\"kind\":\"message\",\"words\":[\"%s\"],\"spec_version\":%d}", id, word, HAPTIC_SPEC_VERSION);
    if (utterance_decode_json(buf, strlen(buf), u) != ZIV_UTT_OK) { printf("fixture %s failed\n", id); exit(2); }
}

static void test_queue(void)
{
    static band_queue q;
    band_queue_init(&q, NULL);
    ziv_utterance u;
    CHECK(band_queue_peek(&q) == NULL, "empty peek is NULL");
    CHECK_EQ(band_queue_pop(&q), BAND_QUEUE_EMPTY, "empty pop");

    make_utt(&u, "utt-0001-aaaa", "one");
    CHECK_EQ(band_queue_push(&q, &u), BAND_QUEUE_OK, "push one");
    CHECK_EQ(band_queue_push(&q, &u), BAND_QUEUE_DUPLICATE, "same id is a duplicate");
    CHECK_EQ(band_queue_count(&q), 1, "duplicate not stored");
    make_utt(&u, "utt-0002-bbbb", "two");
    CHECK_EQ(band_queue_push(&q, &u), BAND_QUEUE_OK, "push two");
    make_utt(&u, "utt-0003-cccc", "three");
    CHECK_EQ(band_queue_push(&q, &u), BAND_QUEUE_OK, "push three");
    CHECK_STR(band_queue_peek(&q)->id, "utt-0001-aaaa", "head is the first");
    CHECK(band_queue_holds(&q, "utt-0002-bbbb"), "holds two");
    CHECK(band_queue_find(&q, "utt-0003-cccc") != NULL, "find three");
    CHECK(band_queue_find(&q, "utt-9999-zzzz") == NULL, "unknown not found");

    const char *ids[BAND_QUEUE_CAP];
    CHECK_EQ(band_queue_ids(&q, ids, BAND_QUEUE_CAP), 3, "three ids listed");
    CHECK_STR(ids[1], "utt-0002-bbbb", "ids in order");

    CHECK_EQ(band_queue_cancel(&q, "utt-0002-bbbb"), BAND_QUEUE_OK, "cancel the middle one");
    CHECK_EQ(band_queue_cancel(&q, "utt-0002-bbbb"), BAND_QUEUE_NOT_FOUND, "cancel twice");
    CHECK_EQ(band_queue_count(&q), 2, "two left");
    CHECK_EQ(band_queue_ids(&q, ids, BAND_QUEUE_CAP), 2, "two ids");
    CHECK_STR(ids[1], "utt-0003-cccc", "order kept after cancel");

    CHECK_EQ(band_queue_ack(&q), BAND_QUEUE_OK, "ack the head");
    CHECK_STR(band_queue_last_acked(&q), "utt-0001-aaaa", "last_acked is the acked head");
    CHECK_STR(band_queue_peek(&q)->id, "utt-0003-cccc", "head advanced");

    /* the cap */
    for (int i = 0; i < BAND_QUEUE_CAP; i++) {
        char id[32]; snprintf(id, sizeof id, "fill-%04d-xxxx", i);
        make_utt(&u, id, "x");
        band_queue_err e = band_queue_push(&q, &u);
        if (i < BAND_QUEUE_CAP - 1) { if (e != BAND_QUEUE_OK) { CHECK(false, "fill push ok"); } }
        else { CHECK_EQ(e, BAND_QUEUE_FULL, "the cap refuses the 21st"); }
    }
    CHECK_EQ(band_queue_count(&q), BAND_QUEUE_CAP, "at the cap");

    /* the ring wraps: pop many, push again */
    for (int i = 0; i < 15; i++) { (void) band_queue_pop(&q); }
    for (int i = 0; i < 10; i++) {
        char id[32]; snprintf(id, sizeof id, "wrap-%04d-xxxx", i);
        make_utt(&u, id, "w");
        CHECK_EQ(band_queue_push(&q, &u), BAND_QUEUE_OK, "push after wrap");
    }
    CHECK_EQ(band_queue_count(&q), 15, "15 held after the wrap");
    CHECK_EQ(band_queue_ids(&q, ids, BAND_QUEUE_CAP), 15, "15 ids");
    CHECK_STR(ids[14], "wrap-0009-xxxx", "last id after the wrap");

    /* the byte image round-trips through the file store */
    static uint8_t blob[BAND_QUEUE_BLOB_MAX];
    size_t len = band_queue_encode(&q, blob, sizeof blob);
    CHECK(len > 0, "encode fits the worst-case blob");
    static band_queue q2;
    band_queue_init(&q2, NULL);
    CHECK_EQ(band_queue_decode(&q2, blob, len), BAND_QUEUE_OK, "decode");
    CHECK_EQ(band_queue_count(&q2), 15, "decoded count");
    CHECK_STR(band_queue_last_acked(&q2), "utt-0001-aaaa", "decoded last_acked");
    const char *ids2[BAND_QUEUE_CAP];
    band_queue_ids(&q2, ids2, BAND_QUEUE_CAP);
    for (int i = 0; i < 15; i++) { if (strcmp(ids[i], ids2[i]) != 0) { CHECK(false, "decoded ids in order"); break; } }
    checks++;
    CHECK_EQ(band_queue_decode(&q2, blob, len - 1), BAND_QUEUE_STORE_ERR, "a short blob is refused");
    blob[0] = 'X';
    CHECK_EQ(band_queue_decode(&q2, blob, len), BAND_QUEUE_STORE_ERR, "a bad magic is refused");
    CHECK_EQ(band_queue_count(&q2), 15, "a refused blob leaves the queue alone");

    /* with a rich utterance (prefix, pending, error flag) */
    ziv_utterance rich;
    CHECK_EQ(utterance_decode_json(k_two_words, strlen(k_two_words), &rich), ZIV_UTT_OK, "rich fixture");
    rich.body_error = true;
    static band_queue q3, q4;
    band_queue_init(&q3, NULL);
    band_queue_push(&q3, &rich);
    len = band_queue_encode(&q3, blob, sizeof blob);
    band_queue_init(&q4, NULL);
    CHECK_EQ(band_queue_decode(&q4, blob, len), BAND_QUEUE_OK, "rich decode");
    const ziv_utterance *back = band_queue_peek(&q4);
    CHECK(back && back->has_prefix && back->mark_len == 3 && back->mark[0] == letter('z'), "prefix survives the image");
    CHECK(back && back->body_error, "body_error survives the image");
    CHECK(back && back->word_count == 2 && back->word_len[1] == 4, "words survive the image");
    CHECK(back && back->tail == HAPTIC_KIND_TAIL_TABLE[HAPTIC_KIND_MESSAGE], "tail recomputed from the kind");

    /* the file store */
    const char *path = getenv("BAND_TEST_QUEUE_FILE");
    if (path == NULL) { path = "band_test_queue.bin"; }
    queue_file_ctx fctx = { path };
    band_queue_store store;
    queue_file_store(&store, &fctx);
    static band_queue q5, q6;
    band_queue_init(&q5, &store);
    band_queue_push(&q5, &rich);
    make_utt(&u, "file-0002-yyyy", "two");
    band_queue_push(&q5, &u);
    band_queue_set_last_acked(&q5, "file-0000-acked");
    CHECK_EQ(band_queue_save(&q5, blob, sizeof blob), BAND_QUEUE_OK, "save to file");
    band_queue_init(&q6, &store);
    CHECK_EQ(band_queue_load(&q6, blob, sizeof blob), BAND_QUEUE_OK, "load from file");
    CHECK_EQ(band_queue_count(&q6), 2, "loaded count");
    CHECK_STR(band_queue_last_acked(&q6), "file-0000-acked", "loaded last_acked");
    CHECK_STR(band_queue_peek(&q6)->id, "golden-message-two-words", "loaded head");
    remove(path);
    band_queue_init(&q6, &store);
    CHECK_EQ(band_queue_load(&q6, blob, sizeof blob), BAND_QUEUE_OK, "no file is an empty queue, not an error");
    CHECK_EQ(band_queue_count(&q6), 0, "empty after a missing file");
}

/* ---- the turn: six_actuator golden ------------------------------------------- */

/* Append the beats of a pattern starting at *t; returns the time after its last gap. */
static int expect_pattern(const rec_beats *r, int i, uint32_t *t, haptic_pattern p, const char *label)
{
    for (uint8_t k = 0; k < HAPTIC_PATTERN_LEN_TABLE[p]; k++) {
        expect_beat(r, i++, *t, 0, HAPTIC_PATTERN_TABLE[p][k].buzz_ms, label);
        *t += HAPTIC_PATTERN_TABLE[p][k].buzz_ms + HAPTIC_PATTERN_TABLE[p][k].gap_after_ms;
    }
    return i;
}

static void test_turn_six_actuator_two_words(void)
{
    rig r;
    rig_init(&r, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    ziv_utterance u;
    CHECK_EQ(utterance_decode_json(k_two_words, strlen(k_two_words), &u), ZIV_UTT_OK, "fixture");
    CHECK(turn_load(&r.t, &u), "load");
    uint32_t end = walk(&r.t, 0);

    /* hand-derived from the tables: prefix (z i v, breath, double-tap), cue
     * (double-tap), taxi, word gap, here, tail gap, end-of-message */
    const uint32_t pace = CELL_GAP_DEFAULT_MS;
    uint32_t t = 0; int i = 0;
    expect_beat(&r.beats, i++, t, HAPTIC_LETTER_MASKS[letter('z')], cell('z'), "prefix:z"); t += cell('z') + pace;
    expect_beat(&r.beats, i++, t, HAPTIC_LETTER_MASKS[letter('i')], cell('i'), "prefix:i"); t += cell('i') + pace;
    expect_beat(&r.beats, i++, t, HAPTIC_LETTER_MASKS[letter('v')], cell('v'), "prefix:v"); t += cell('v') + PREFIX_BREATH_MS;
    i = expect_pattern(&r.beats, i, &t, HAPTIC_KIND_TAIL_TABLE[HAPTIC_KIND_MESSAGE], "tail");
    i = expect_pattern(&r.beats, i, &t, HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_MESSAGE], "cue");
    const char *w0 = "taxi", *w1 = "here";
    for (int k = 0; w0[k]; k++) {
        char lab[8]; snprintf(lab, sizeof lab, "cell:%c", w0[k]);
        expect_beat(&r.beats, i++, t, HAPTIC_LETTER_MASKS[letter(w0[k])], cell(w0[k]), lab);
        t += cell(w0[k]) + (w0[k + 1] ? pace : WORD_GAP_MS);
    }
    for (int k = 0; w1[k]; k++) {
        char lab[8]; snprintf(lab, sizeof lab, "cell:%c", w1[k]);
        expect_beat(&r.beats, i++, t, HAPTIC_LETTER_MASKS[letter(w1[k])], cell(w1[k]), lab);
        t += cell(w1[k]) + (w1[k + 1] ? pace : TAIL_GAP_MS);
    }
    i = expect_pattern(&r.beats, i, &t, HAPTIC_PAT_END_OF_MESSAGE, "close");
    CHECK_EQ(r.beats.n, i, "beat count = prefix + cue + 8 cells + close");
    CHECK_EQ(end, t, "the utterance ends after the close's tail gap");
    CHECK_EQ(turn_last_result(&r.t), TURN_RESULT_PLAYED, "played");
    CHECK_EQ(turn_closed_ms(&r.t), t, "closed_ms is the end");
    CHECK_EQ(turn_started_ms(&r.t), 0, "started_ms is the first beat");

    /* the phase events, in order */
    CHECK_EQ(r.events.n, 5, "cue, word 0, word 1, close, done");
    CHECK(r.events.n >= 5 && r.events.e[0].phase == TURN_PHASE_CUE, "event 0 cue");
    CHECK(r.events.n >= 5 && r.events.e[1].phase == TURN_PHASE_WORD && r.events.e[1].wi == 0 && strcmp(r.events.e[1].label, "taxi") == 0, "event 1 word 0 taxi");
    CHECK(r.events.n >= 5 && r.events.e[2].phase == TURN_PHASE_WORD && r.events.e[2].wi == 1 && strcmp(r.events.e[2].label, "here") == 0, "event 2 word 1 here");
    CHECK(r.events.n >= 5 && r.events.e[3].phase == TURN_PHASE_CLOSE, "event 3 close");
    CHECK(r.events.n >= 5 && r.events.e[4].phase == TURN_PHASE_DONE, "event 4 done");
    for (int ch = 0; ch < 6; ch++) { CHECK_EQ(mock_drive(&r.mock, (uint8_t) ch), 0, "silent after the turn"); }
}

/* ---- the turn: single_actuator golden ---------------------------------------- */

/* slot start offsets within a cell, as the spec defines them */
static void slot_offsets(uint32_t *off, uint32_t *cell_end)
{
    uint32_t t = 0;
    for (int i = 0; i < HAPTIC_SLOT_COUNT; i++) {
        off[i] = t;
        t += SLOT_MS;
        if (i < HAPTIC_SLOT_COUNT - 1) { t += SLOT_GAP_MS; }
        if (i == HAPTIC_SLOT_COUNT / 2 - 1) { t += COLUMN_GAP_MS; }
    }
    *cell_end = t;
}

/* expect a slot cell for `c` starting at *t; returns the next beat index */
static int expect_slot_cell(const rec_beats *r, int i, uint32_t *t, char c, const char *label)
{
    uint32_t off[HAPTIC_SLOT_COUNT], end;
    slot_offsets(off, &end);
    uint8_t mask = HAPTIC_LETTER_MASKS[letter(c)];
    for (int s = 0; s < HAPTIC_SLOT_COUNT; s++) {
        uint8_t bit = (uint8_t) (1u << (HAPTIC_SLOT_ORDER[s] - 1));
        if (mask & bit) { expect_beat(r, i++, *t + off[s], bit, SLOT_MS, label); }
    }
    *t += end;
    return i;
}

static void test_turn_single_actuator_hello(void)
{
    rig r;
    rig_init(&r, TURN_PROFILE_SINGLE_ACTUATOR, CELL_GAP_DEFAULT_MS);
    ziv_utterance u;
    CHECK_EQ(utterance_decode_json(k_hello_word, strlen(k_hello_word), &u), ZIV_UTT_OK, "fixture");
    CHECK(turn_load(&r.t, &u), "load");
    uint32_t end = walk(&r.t, 0);

    uint32_t off[HAPTIC_SLOT_COUNT], cell_end;
    slot_offsets(off, &cell_end);
    CHECK_EQ(cell_end, HAPTIC_SLOT_CELL_MS, "slot cell duration matches the generated constant");

    const uint32_t pace = CELL_GAP_DEFAULT_MS;
    uint32_t t = 0; int i = 0;
    i = expect_slot_cell(&r.beats, i, &t, 'z', "prefix:z"); t += pace;
    i = expect_slot_cell(&r.beats, i, &t, 'i', "prefix:i"); t += pace;
    i = expect_slot_cell(&r.beats, i, &t, 'v', "prefix:v"); t += PREFIX_BREATH_MS;
    i = expect_pattern(&r.beats, i, &t, HAPTIC_KIND_TAIL_TABLE[HAPTIC_KIND_MESSAGE], "tail");
    i = expect_pattern(&r.beats, i, &t, HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_MESSAGE], "cue");
    const char *w = "hello";
    for (int k = 0; w[k]; k++) {
        char lab[8]; snprintf(lab, sizeof lab, "cell:%c", w[k]);
        i = expect_slot_cell(&r.beats, i, &t, w[k], lab);
        t += w[k + 1] ? pace : TAIL_GAP_MS;
    }
    i = expect_pattern(&r.beats, i, &t, HAPTIC_PAT_END_OF_MESSAGE, "close");
    CHECK_EQ(r.beats.n, i, "single-actuator beat count");
    CHECK_EQ(end, t, "single-actuator end time");
    /* 'i' (dots 2,4) has no dot 1: its first slot is silent, carried by the
     * previous beat's gap — a beat list cannot start with silence */
    CHECK(r.beats.n > 4 && r.beats.b[4].mask == 0x02 && r.beats.b[4].at == cell_end + pace + off[1], "leading slot silence of i carried on the previous gap");
}

static void test_turn_single_actuator_leading_silence_segment(void)
{
    /* A word whose FIRST letter has no dot 1 ('i') follows the cue: the
     * segment itself must start late by the leading slot offset. */
    rig r;
    rig_init(&r, TURN_PROFILE_SINGLE_ACTUATOR, CELL_GAP_MIN_MS);
    ziv_utterance u;
    make_utt(&u, "lead-silence-0001", "it");
    CHECK(turn_load(&r.t, &u), "load");
    (void) walk(&r.t, 0);
    uint32_t off[HAPTIC_SLOT_COUNT], cell_end;
    slot_offsets(off, &cell_end);
    uint32_t t = 0; int i = 0;
    i = expect_pattern(&r.beats, i, &t, HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_MESSAGE], "cue");
    i = expect_slot_cell(&r.beats, i, &t, 'i', "cell:i"); t += CELL_GAP_MIN_MS;
    i = expect_slot_cell(&r.beats, i, &t, 't', "cell:t"); t += TAIL_GAP_MS;
    i = expect_pattern(&r.beats, i, &t, HAPTIC_PAT_END_OF_MESSAGE, "close");
    CHECK_EQ(r.beats.n, i, "beat count with a leading-silence word");
}

/* ---- pending body, timeout, error ------------------------------------------ */

static void test_turn_body_pending(void)
{
    /* the body arrives during the first working wait */
    rig r;
    rig_init(&r, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    ziv_utterance u;
    CHECK_EQ(utterance_decode_json(k_pending, strlen(k_pending), &u), ZIV_UTT_OK, "fixture");
    CHECK(turn_load(&r.t, &u), "load");
    uint32_t now = 0;
    uint32_t cue_len = 0;
    for (uint8_t k = 0; k < HAPTIC_PATTERN_LEN_TABLE[HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_REMINDER]]; k++) {
        cue_len += HAPTIC_PATTERN_TABLE[HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_REMINDER]][k].buzz_ms
                 + HAPTIC_PATTERN_TABLE[HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_REMINDER]][k].gap_after_ms;
    }
    uint32_t working_len = 0;
    for (uint8_t k = 0; k < HAPTIC_PROCESSING_LEN; k++) { working_len += HAPTIC_PROCESSING[k].buzz_ms + HAPTIC_PROCESSING[k].gap_after_ms; }

    /* walk until the sequencer is idle between repeats */
    for (int guard = 0; guard < 1000; guard++) {
        uint32_t next = turn_step(&r.t, now);
        if (r.t.waiting_body) { break; }
        if (next > now) { now = next; }
    }
    CHECK(r.t.waiting_body, "waiting between working repeats");
    CHECK_EQ(now, cue_len + working_len, "first working play done after cue + processing");
    CHECK_EQ(turn_step(&r.t, now), cue_len + WORKING_EVERY_MS, "next repeat is WORKING_EVERY_MS after the first started");
    CHECK_EQ(r.events.n, 2, "cue and working reported");
    CHECK(r.events.n >= 2 && r.events.e[1].phase == TURN_PHASE_WORKING, "working event");

    /* a second repeat happens before the body */
    now = cue_len + WORKING_EVERY_MS;
    (void) turn_step(&r.t, now);
    CHECK(haptic_out_is_playing(&r.h), "second working repeat started on time");
    CHECK_EQ(r.beats.n, HAPTIC_PATTERN_LEN_TABLE[HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_REMINDER]] + 2 * HAPTIC_PROCESSING_LEN - HAPTIC_PROCESSING_LEN + 1,
             "beats so far: cue + first working + first beat of the second");
    CHECK_EQ(r.events.n, 2, "working is reported once, not per repeat");

    /* the body arrives mid-repeat: words start when the repeat ends */
    const char *ws[2] = { "meds", "nine" };
    CHECK_EQ(turn_set_body(&r.t, ws, 2), ZIV_UTT_OK, "body set");
    uint32_t end = walk(&r.t, now);
    uint32_t words_start = cue_len + WORKING_EVERY_MS + working_len;
    int first_cell = -1;
    for (int i = 0; i < r.beats.n; i++) { if (strncmp(r.beats.b[i].label, "cell:", 5) == 0) { first_cell = i; break; } }
    CHECK(first_cell >= 0, "cells played after the body");
    CHECK(first_cell >= 0 && r.beats.b[first_cell].at == words_start, "first cell right after the repeat's tail gap");
    CHECK(first_cell >= 0 && r.beats.b[first_cell].mask == HAPTIC_LETTER_MASKS[letter('m')], "first cell is m");
    CHECK_EQ(turn_last_result(&r.t), TURN_RESULT_PLAYED, "played after the body");
    uint32_t expect_end = words_start;
    const char *w0 = "meds", *w1 = "nine";
    for (int k = 0; w0[k]; k++) { expect_end += cell(w0[k]) + (w0[k + 1] ? CELL_GAP_DEFAULT_MS : WORD_GAP_MS); }
    for (int k = 0; w1[k]; k++) { expect_end += cell(w1[k]) + (w1[k + 1] ? CELL_GAP_DEFAULT_MS : TAIL_GAP_MS); }
    for (uint8_t k = 0; k < HAPTIC_END_OF_MESSAGE_LEN; k++) { expect_end += HAPTIC_END_OF_MESSAGE[k].buzz_ms + HAPTIC_END_OF_MESSAGE[k].gap_after_ms; }
    CHECK_EQ(end, expect_end, "end after words + close");
    CHECK(r.events.n >= 5 && r.events.e[2].phase == TURN_PHASE_WORD && r.events.e[2].wi == 0, "word 0 after working");
    CHECK(r.events.n >= 5 && r.events.e[r.events.n - 1].phase == TURN_PHASE_DONE, "done");

    /* the body arrives while idle between repeats: words start at once */
    rig r2;
    rig_init(&r2, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r2.t, &u), "load 2");
    now = 0;
    for (int guard = 0; guard < 1000; guard++) {
        uint32_t next = turn_step(&r2.t, now);
        if (r2.t.waiting_body) { break; }
        if (next > now) { now = next; }
    }
    uint32_t idle_at = now + (WORKING_EVERY_MS - working_len) / 2;
    CHECK_EQ(turn_set_body(&r2.t, ws, 2), ZIV_UTT_OK, "body set while idle");
    (void) turn_step(&r2.t, idle_at);
    int fc = -1;
    for (int i = 0; i < r2.beats.n; i++) { if (strncmp(r2.beats.b[i].label, "cell:", 5) == 0) { fc = i; break; } }
    CHECK(fc >= 0 && r2.beats.b[fc].at == idle_at, "idle body: first cell at the body's arrival");

    /* an empty body (the header-only render): close right after working */
    rig r3;
    rig_init(&r3, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r3.t, &u), "load 3");
    now = 0;
    for (int guard = 0; guard < 1000; guard++) {   /* until the working phase starts (as the player does) */
        uint32_t next = turn_step(&r3.t, now);
        if (r3.events.n >= 2 && r3.events.e[1].phase == TURN_PHASE_WORKING) { break; }
        if (next > now) { now = next; }
    }
    CHECK_EQ(turn_set_body(&r3.t, NULL, 0), ZIV_UTT_OK, "empty body accepted");
    end = walk(&r3.t, now);
    uint32_t close_len = 0;
    for (uint8_t k = 0; k < HAPTIC_END_OF_MESSAGE_LEN; k++) { close_len += HAPTIC_END_OF_MESSAGE[k].buzz_ms + HAPTIC_END_OF_MESSAGE[k].gap_after_ms; }
    CHECK_EQ(end, cue_len + working_len + close_len, "empty body: cue, one working, close");
    CHECK_EQ(turn_last_result(&r3.t), TURN_RESULT_PLAYED, "empty body plays to the close");

    /* a body that is already here when the cue ends needs no working pattern */
    rig r3b;
    rig_init(&r3b, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r3b.t, &u), "load 3b");
    (void) turn_step(&r3b.t, 0);
    CHECK_EQ(turn_set_body(&r3b.t, ws, 2), ZIV_UTT_OK, "early body");
    (void) walk(&r3b.t, 0);
    CHECK(r3b.events.n >= 2 && r3b.events.e[1].phase == TURN_PHASE_WORD, "early body: words right after the cue, no working");

    /* timeout: after TURN_BODY_TIMEOUT_REPEATS repeats, the error pattern then FAILED */
    rig r4;
    rig_init(&r4, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r4.t, &u), "load 4");
    end = walk(&r4.t, 0);
    CHECK_EQ(turn_last_result(&r4.t), TURN_RESULT_BODY_TIMEOUT, "body timeout");
    CHECK_STR(turn_result_name(turn_last_result(&r4.t)), "body_timeout", "nack reason body_timeout");
    CHECK_EQ(r4.t.working_repeats, TURN_BODY_TIMEOUT_REPEATS, "exactly the timeout count of repeats");
    uint32_t err_len = 0;
    haptic_pattern errp = HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_ERROR];
    for (uint8_t k = 0; k < HAPTIC_PATTERN_LEN_TABLE[errp]; k++) { err_len += HAPTIC_PATTERN_TABLE[errp][k].buzz_ms + HAPTIC_PATTERN_TABLE[errp][k].gap_after_ms; }
    CHECK_EQ(end, cue_len + (uint32_t) (TURN_BODY_TIMEOUT_REPEATS - 1) * WORKING_EVERY_MS + working_len + err_len,
             "timeout end: cue + (N-1) periods + the last working + the error pattern");
    CHECK(r4.events.n >= 1 && r4.events.e[r4.events.n - 1].phase == TURN_PHASE_FAILED, "failed event");
    CHECK_STR(r4.beats.b[r4.beats.n - 1].label, "error", "last beat is the error pattern");

    /* the relay's error body: the error pattern, FAILED with the relay's reason */
    rig r5;
    rig_init(&r5, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r5.t, &u), "load 5");
    (void) turn_step(&r5.t, 0);
    turn_set_body_error(&r5.t);
    end = walk(&r5.t, 0);
    CHECK_EQ(turn_last_result(&r5.t), TURN_RESULT_BODY_ERROR, "body error result");
    CHECK_EQ(end, cue_len + err_len, "error body: cue then the error pattern (no working needed)");
}

/* ---- controls, announce, pace ---------------------------------------------- */

static void test_turn_controls(void)
{
    ziv_utterance u;
    CHECK_EQ(utterance_decode_json(k_two_words, strlen(k_two_words), &u), ZIV_UTT_OK, "fixture");

    /* STOP silences and keeps the utterance; REPLAY restarts from the first beat */
    rig r;
    rig_init(&r, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r.t, &u), "load");
    uint32_t now = 0;
    for (int k = 0; k < 6; k++) { uint32_t n = turn_step(&r.t, now); if (n > now) { now = n; } }
    CHECK(haptic_out_is_playing(&r.h), "playing before stop");
    turn_control(&r.t, TURN_CTL_STOP, now);
    for (int ch = 0; ch < 6; ch++) { CHECK_EQ(mock_drive(&r.mock, (uint8_t) ch), 0, "stop silences"); }
    CHECK_EQ(turn_step(&r.t, now + 1), 0, "stopped: nothing scheduled");
    CHECK(turn_is_loaded(&r.t) && turn_is_active(&r.t), "stopped utterance stays loaded");
    r.beats.n = 0;
    turn_control(&r.t, TURN_CTL_REPLAY, now);
    uint32_t base = now;
    uint32_t end = walk(&r.t, now);
    CHECK(r.beats.n > 0 && r.beats.b[0].at == base && r.beats.b[0].mask == HAPTIC_LETTER_MASKS[letter('z')], "replay starts with the prefix z");
    CHECK_EQ(turn_last_result(&r.t), TURN_RESULT_PLAYED, "replay plays through");
    (void) end;

    /* SKIP during word 0 goes to word 1 */
    rig r2;
    rig_init(&r2, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r2.t, &u), "load 2");
    now = 0;
    for (int guard = 0; guard < 1000; guard++) {
        uint32_t n = turn_step(&r2.t, now);
        if (r2.t.seg == TURN_SEG_WORD && r2.t.word_idx == 0 && r2.beats.n > 0 && strcmp(r2.beats.b[r2.beats.n - 1].label, "cell:t") == 0) { break; }
        if (n > now) { now = n; }
    }
    CHECK_EQ(r2.t.word_idx, 0, "in word 0");
    turn_control(&r2.t, TURN_CTL_SKIP, now);
    int before = r2.beats.n;
    (void) turn_step(&r2.t, now);
    CHECK(r2.beats.n == before + 1 && strcmp(r2.beats.b[before].label, "cell:h") == 0 && r2.beats.b[before].at == now, "skip: word 1 starts now with h");
    CHECK(r2.events.n >= 1 && r2.events.e[r2.events.n - 1].phase == TURN_PHASE_WORD && r2.events.e[r2.events.n - 1].wi == 1, "skip reports word 1");
    (void) walk(&r2.t, now);
    CHECK_EQ(turn_last_result(&r2.t), TURN_RESULT_PLAYED, "skip then plays through");

    /* REPLAY_WORD during word 1 restarts word 1 */
    rig r3;
    rig_init(&r3, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r3.t, &u), "load 3");
    now = 0;
    for (int guard = 0; guard < 1000; guard++) {
        uint32_t n = turn_step(&r3.t, now);
        if (r3.t.seg == TURN_SEG_WORD && r3.t.word_idx == 1 && r3.beats.n > 0 && strcmp(r3.beats.b[r3.beats.n - 1].label, "cell:e") == 0) { break; }
        if (n > now) { now = n; }
    }
    turn_control(&r3.t, TURN_CTL_REPLAY_WORD, now);
    before = r3.beats.n;
    (void) turn_step(&r3.t, now);
    CHECK(r3.beats.n == before + 1 && strcmp(r3.beats.b[before].label, "cell:h") == 0, "replay_word: word 1 restarts with h");
    (void) walk(&r3.t, now);
    CHECK_EQ(turn_last_result(&r3.t), TURN_RESULT_PLAYED, "replay_word then plays through");

    /* ADVANCE mid-play: FAILED cancelled_by_wearer, silent, released */
    rig r4;
    rig_init(&r4, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r4.t, &u), "load 4");
    now = 0;
    for (int k = 0; k < 6; k++) { uint32_t n = turn_step(&r4.t, now); if (n > now) { now = n; } }
    turn_control(&r4.t, TURN_CTL_ADVANCE, now);
    CHECK_EQ(turn_last_result(&r4.t), TURN_RESULT_CANCELLED, "advance mid-play cancels");
    CHECK_STR(turn_result_name(turn_last_result(&r4.t)), "cancelled_by_wearer", "nack reason");
    CHECK(!turn_is_active(&r4.t), "not active after advance");
    for (int ch = 0; ch < 6; ch++) { CHECK_EQ(mock_drive(&r4.mock, (uint8_t) ch), 0, "advance silences"); }
    CHECK(r4.events.n >= 1 && r4.events.e[r4.events.n - 1].phase == TURN_PHASE_FAILED, "failed event on advance");
    turn_release(&r4.t);
    CHECK(!turn_is_loaded(&r4.t), "released");
    CHECK(turn_load(&r4.t, &u), "loads again after release");

    /* announce: another utterance's cue between two words */
    rig r5;
    rig_init(&r5, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    CHECK(turn_load(&r5.t, &u), "load 5");
    now = 0;
    for (int guard = 0; guard < 1000; guard++) {
        uint32_t n = turn_step(&r5.t, now);
        if (r5.t.seg == TURN_SEG_WORD && r5.t.word_idx == 0) { break; }
        if (n > now) { now = n; }
    }
    turn_announce(&r5.t, HAPTIC_KIND_REMINDER);
    (void) walk(&r5.t, now);
    int announce_at = -1;
    for (int i = 0; i < r5.beats.n; i++) { if (strcmp(r5.beats.b[i].label, "announce") == 0) { announce_at = i; break; } }
    CHECK(announce_at > 0, "announce beats present");
    CHECK(announce_at > 0 && strcmp(r5.beats.b[announce_at - 1].label, "cell:i") == 0, "announce follows the last cell of taxi");
    int after = announce_at + HAPTIC_PATTERN_LEN_TABLE[HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_REMINDER]];
    CHECK(after < r5.beats.n && strcmp(r5.beats.b[after].label, "cell:h") == 0, "here follows the announce");
    CHECK(announce_at > 0 && r5.beats.b[announce_at].buzz == HAPTIC_PATTERN_TABLE[HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_REMINDER]][0].buzz_ms, "announce is the reminder's cue");
    CHECK_EQ(turn_last_result(&r5.t), TURN_RESULT_PLAYED, "announce then plays through");
    rig r6;
    rig_init(&r6, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    turn_announce(&r6.t, HAPTIC_KIND_MESSAGE);
    CHECK_EQ(r6.t.announce_kind, -1, "announce is ignored when idle (its own turn will cue it)");

    /* pace: clamped, applied at the next segment */
    rig r7;
    rig_init(&r7, TURN_PROFILE_SIX_ACTUATOR, 10);
    CHECK_EQ(turn_pace(&r7.t), CELL_GAP_MIN_MS, "pace clamps up");
    CHECK_EQ(haptic_out_cell_gap_ms(&r7.h), CELL_GAP_MIN_MS, "sequencer pace follows");
    CHECK_EQ(turn_set_pace(&r7.t, 9999), CELL_GAP_MAX_MS, "pace clamps down");
    ziv_utterance reply;
    CHECK_EQ(utterance_decode_json(k_reply, strlen(k_reply), &reply), ZIV_UTT_OK, "reply fixture");
    CHECK(turn_load(&r7.t, &reply), "load reply");
    (void) walk(&r7.t, 0);
    uint32_t cue_len = 0;
    for (uint8_t k = 0; k < HAPTIC_DOUBLE_TAP_LEN; k++) { cue_len += HAPTIC_DOUBLE_TAP[k].buzz_ms + HAPTIC_DOUBLE_TAP[k].gap_after_ms; }
    expect_beat(&r7.beats, 2, cue_len, HAPTIC_LETTER_MASKS[letter('y')], cell('y'), "cell:y");
    expect_beat(&r7.beats, 3, cue_len + cell('y') + CELL_GAP_MAX_MS, HAPTIC_LETTER_MASKS[letter('e')], cell('e'), "cell:e");
}

/* ---- beat mode: a compiled word equals a WORD play -------------------------- */

static void test_turn_beats_equal_word_play(void)
{
    rig r;
    rig_init(&r, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    ziv_utterance u;
    make_utt(&u, "beats-vs-word-01", "ziv");
    r.t.utt = u;   /* compile without playing */
    turn_compile_word(&r.t, 0);
    CHECK_EQ(r.t.nbeats, 3, "ziv compiles to 3 beats on six_actuator");

    /* the word play, recorded */
    typedef struct { uint32_t at, buzz, gap; uint8_t mask; } wb;
    wb a[8], b[8];
    int na = 0, nb = 0;
    uint32_t now = 0;
    CHECK_EQ(haptic_out_play_word(&r.h, "ziv"), HAPTIC_OK, "word ziv");
    for (int guard = 0; guard < 100; guard++) {
        haptic_out_event_t ev = (haptic_out_event_t) 0xFF; haptic_out_step_t st = {0};
        uint32_t next = haptic_out_step(&r.h, now, &ev, &st);
        if (ev == HAPTIC_OUT_EV_START) { continue; }
        if (ev == HAPTIC_OUT_EV_BUZZ && na < 8) { a[na].at = now; a[na].buzz = st.buzz_ms; a[na].gap = st.gap_after_ms; a[na].mask = st.dot_mask; na++; }
        if (ev == HAPTIC_OUT_EV_END || next == 0) { break; }
        now = next;
    }
    now = 0;
    CHECK_EQ(haptic_out_play_beats(&r.h, r.t.beats, r.t.nbeats), HAPTIC_OK, "compiled beats");
    for (int guard = 0; guard < 100; guard++) {
        haptic_out_event_t ev = (haptic_out_event_t) 0xFF; haptic_out_step_t st = {0};
        uint32_t next = haptic_out_step(&r.h, now, &ev, &st);
        if (ev == HAPTIC_OUT_EV_START) { continue; }
        if (ev == HAPTIC_OUT_EV_BUZZ && nb < 8) { b[nb].at = now; b[nb].buzz = st.buzz_ms; b[nb].gap = st.gap_after_ms; b[nb].mask = st.dot_mask; nb++; }
        if (ev == HAPTIC_OUT_EV_END || next == 0) { break; }
        now = next;
    }
    CHECK_EQ(na, 3, "word play 3 beats");
    CHECK_EQ(nb, na, "compiled list same beat count");
    for (int i = 0; i < na && i < nb; i++) {
        CHECK_EQ(b[i].at, a[i].at, "turn beats / word: start");
        CHECK_EQ(b[i].buzz, a[i].buzz, "turn beats / word: buzz");
        CHECK_EQ(b[i].gap, a[i].gap, "turn beats / word: gap");
        CHECK_EQ(b[i].mask, a[i].mask, "turn beats / word: mask");
    }
    /* and the single-actuator compile of a 32-letter word stays within the bound */
    rig r2;
    rig_init(&r2, TURN_PROFILE_SINGLE_ACTUATOR, CELL_GAP_DEFAULT_MS);
    char long_word[1024];
    snprintf(long_word, sizeof long_word, "{\"id\":\"long-word-single-1\",\"kind\":\"message\",\"words\":[\"%s\"],\"spec_version\":%d}",
             "qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq", HAPTIC_SPEC_VERSION);   /* q = 5 dots, the densest */
    CHECK_EQ(utterance_decode_json(long_word, strlen(long_word), &r2.t.utt), ZIV_UTT_OK, "32 q's");
    turn_compile_word(&r2.t, 0);
    CHECK_EQ(r2.t.nbeats, 32 * HAPTIC_LETTER_DOTS[letter('q')], "32 × 5 beats");
    CHECK(r2.t.nbeats <= TURN_BEATS_MAX, "within the bounded buffer");
}

/* ---- the transport against a scripted frame adapter -------------------------- */

typedef struct {
    int connect_rc;            /* what connect() returns */
    int connects;
    int closes;
    char sent[96][2048];
    int nsent;
    const char *inbox[64];
    int ninbox, inbox_pos;
} fake_io_t;

static int fio_connect(void *ctx) { fake_io_t *f = (fake_io_t *) ctx; f->connects++; return f->connect_rc; }
static int fio_send(void *ctx, const char *text, size_t len)
{
    fake_io_t *f = (fake_io_t *) ctx;
    if (f->nsent >= 96 || len >= sizeof f->sent[0]) { return -1; }
    memcpy(f->sent[f->nsent], text, len);
    f->sent[f->nsent][len] = '\0';
    f->nsent++;
    return 0;
}
static int fio_recv(void *ctx, char *buf, size_t cap, uint32_t timeout_ms)
{
    (void) timeout_ms;
    fake_io_t *f = (fake_io_t *) ctx;
    if (f->inbox_pos >= f->ninbox) { return 0; }
    const char *s = f->inbox[f->inbox_pos++];
    if (s == NULL) { return -1; }   /* a NULL in the inbox = the link drops */
    size_t n = strlen(s);
    if (n + 1 > cap) { return -1; }
    memcpy(buf, s, n + 1);
    return (int) n;
}
static void fio_close(void *ctx) { ((fake_io_t *) ctx)->closes++; }

static void fio_init(fake_io_t *f, band_frame_io *io)
{
    memset(f, 0, sizeof *f);
    io->connect = fio_connect; io->send_frame = fio_send; io->recv_frame = fio_recv; io->close = fio_close; io->ctx = f;
}
static void fio_push(fake_io_t *f, const char *frame) { if (f->ninbox < 64) { f->inbox[f->ninbox++] = frame; } }

typedef struct {
    fake_io_t io; band_frame_io vt; mock_drv mock; drv2605_bus bus; haptic_out h; turn t; band_queue q;
    band_transport tr; band_transport_config cfg; rec_beats beats;
} trig;

static void trig_init_pings(trig *r, const char *key, uint32_t ping_every_ms);

/* By default the pings are pushed far out so frame counts are the utterances' own. */
static void trig_init(trig *r, const char *key)
{
    trig_init_pings(r, key, (uint32_t) WORKING_EVERY_MS * 100000u);
}

static void trig_init_pings(trig *r, const char *key, uint32_t ping_every_ms)
{
    fio_init(&r->io, &r->vt);
    mock_init(&r->mock); mock_bus(&r->bus, &r->mock);
    haptic_out_init(&r->h, &r->bus);
    turn_init(&r->t, &r->h, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    r->beats.n = 0;
    turn_set_callbacks(&r->t, NULL, NULL, rec_on_beat, &r->beats);
    band_queue_init(&r->q, NULL);
    memset(&r->cfg, 0, sizeof r->cfg);
    r->cfg.device_key = key;
    r->cfg.profile = TURN_PROFILE_SIX_ACTUATOR;
    r->cfg.seed = 12345;
    r->cfg.ping_every_ms = ping_every_ms;
    transport_init(&r->tr, &r->vt, &r->q, &r->t, &r->cfg);
}

/* parse sent frame i */
static cJSON *sent(trig *r, int i) { return (i < r->io.nsent) ? cJSON_Parse(r->io.sent[i]) : NULL; }
static const char *jstr(cJSON *o, const char *k) { cJSON *v = o ? cJSON_GetObjectItemCaseSensitive(o, k) : NULL; return cJSON_IsString(v) ? v->valuestring : NULL; }
static double jnum(cJSON *o, const char *k) { cJSON *v = o ? cJSON_GetObjectItemCaseSensitive(o, k) : NULL; return cJSON_IsNumber(v) ? v->valuedouble : -1; }

/* walk the transport on a virtual clock until nothing is scheduled or the clock passes `until` */
static uint32_t twalk(trig *r, uint32_t now, uint32_t until)
{
    for (int guard = 0; guard < 100000; guard++) {
        uint32_t next = transport_step(&r->tr, now);
        if (next == 0 || next > until) { return now; }
        if (next > now) { now = next; }
        else { now++; }
    }
    return now;
}

static const char *k_ack =
    "{\"type\":\"hello.ack\",\"v\":1,\"wearer\":\"w_1\",\"device\":\"d_1\",\"spec_version\":4,"
    "\"prefs\":{\"pace_ms\":300,\"advance\":\"auto\"},\"resend\":[]}";

static void test_transport_hello_and_play(void)
{
    trig r;
    trig_init(&r, "band-test-key-0123456789");
    /* the ack carries a resend; then an open */
    static char ack[2048];
    snprintf(ack, sizeof ack, "{\"type\":\"hello.ack\",\"v\":1,\"wearer\":\"w_1\",\"device\":\"d_1\",\"spec_version\":%d,"
             "\"prefs\":{\"pace_ms\":300,\"advance\":\"auto\"},\"resend\":[%s]}", HAPTIC_SPEC_VERSION, k_reply);
    fio_push(&r.io, ack);
    static char open_frame[2048];
    snprintf(open_frame, sizeof open_frame, "{\"type\":\"utterance.open\",\"utterance\":%s}", k_two_words);
    fio_push(&r.io, open_frame);

    uint32_t now = 0;
    (void) transport_step(&r.tr, now);
    CHECK_EQ(r.io.connects, 1, "connected on the first step");
    CHECK(r.io.nsent >= 1, "hello sent");
    cJSON *hello = sent(&r, 0);
    CHECK_STR(jstr(hello, "type"), "hello", "hello type");
    CHECK_EQ(jnum(hello, "v"), ZIV_WIRE_VERSION, "hello v");
    CHECK_STR(jstr(hello, "device_key"), "band-test-key-0123456789", "hello device_key");
    CHECK_STR(jstr(hello, "profile"), "six_actuator", "hello profile");
    CHECK_EQ(jnum(hello, "spec_version"), HAPTIC_SPEC_VERSION, "hello spec_version");
    CHECK_EQ(jnum(hello, "pace_ms"), CELL_GAP_DEFAULT_MS, "hello pace_ms");
    CHECK(cJSON_GetObjectItemCaseSensitive(hello, "last_acked") == NULL, "no last_acked on a fresh device");
    cJSON *held = cJSON_GetObjectItemCaseSensitive(hello, "held");
    CHECK(cJSON_IsArray(held) && cJSON_GetArraySize(held) == 0, "held is an empty array");
    cJSON_Delete(hello);

    CHECK_EQ(transport_state(&r.tr), TRANSPORT_READY, "ready after the ack");
    CHECK_EQ(turn_pace(&r.t), 300, "prefs.pace applied");
    CHECK_STR(r.tr.wearer, "w_1", "wearer from the ack");
    /* the resend and the open are both held (2), the first already loaded */
    CHECK(turn_is_loaded(&r.t), "the queue head loaded at once (advance auto)");
    CHECK_EQ(band_queue_count(&r.q), 2, "two held");

    now = twalk(&r, now, 60000);
    CHECK_EQ(band_queue_count(&r.q), 0, "both played and acknowledged");
    CHECK_STR(band_queue_last_acked(&r.q), "golden-message-two-words", "last_acked is the second");
    /* frames: hello, then for the reply: cue, word 0, close, played; then two_words: cue, word 0, word 1, close, played */
    const char *want[][3] = {
        {"progress", "golden-reply-no-prefix", "cue"}, {"progress", "golden-reply-no-prefix", "word"},
        {"progress", "golden-reply-no-prefix", "close"}, {"played", "golden-reply-no-prefix", NULL},
        {"progress", "golden-message-two-words", "cue"}, {"progress", "golden-message-two-words", "word"},
        {"progress", "golden-message-two-words", "word"}, {"progress", "golden-message-two-words", "close"},
        {"played", "golden-message-two-words", NULL},
    };
    CHECK_EQ(r.io.nsent, 1 + 9, "hello + 9 frames");
    for (int i = 0; i < 9 && 1 + i < r.io.nsent; i++) {
        cJSON *f = sent(&r, 1 + i);
        CHECK_STR(jstr(f, "type"), want[i][0], "frame type in order");
        CHECK_STR(jstr(f, "id"), want[i][1], "frame id in order");
        if (want[i][2]) { CHECK_STR(jstr(f, "phase"), want[i][2], "frame phase in order"); }
        cJSON_Delete(f);
    }
    cJSON *w1 = sent(&r, 1 + 6);
    CHECK_EQ(jnum(w1, "word_index"), 1, "second word carries word_index 1");
    cJSON_Delete(w1);
    cJSON *w0 = sent(&r, 1 + 1);
    CHECK_EQ(jnum(w0, "word_index"), 0, "first word carries word_index 0");
    cJSON *c0 = sent(&r, 1 + 2);
    CHECK(cJSON_GetObjectItemCaseSensitive(c0, "word_index") == NULL, "close has no word_index");
    cJSON_Delete(w0); cJSON_Delete(c0);
    cJSON *pl = sent(&r, 1 + 8);
    CHECK(jnum(pl, "started_ms") >= 0 && jnum(pl, "closed_ms") > jnum(pl, "started_ms"), "played carries monotonic start/close");
    cJSON_Delete(pl);
    CHECK_EQ(r.tr.n.played, 2, "two played counted");
    /* pace 300 was used: the first cell of "yes" is y then e, pace apart */
    int yi = -1;
    for (int i = 0; i < r.beats.n; i++) { if (strcmp(r.beats.b[i].label, "cell:y") == 0) { yi = i; break; } }
    CHECK(yi >= 0 && yi + 1 < r.beats.n && r.beats.b[yi + 1].at == r.beats.b[yi].at + cell('y') + 300, "relay pace 300 inside the word");
}

static void test_transport_nacks_and_cancel(void)
{
    trig r;
    trig_init(&r, "band-test-key-0123456789");
    fio_push(&r.io, k_ack);
    /* spec mismatch → nack spec_mismatch with the id */
    static char bad[1024], frame[2048];
    with_spec(bad, sizeof bad, "spec-old-000001", HAPTIC_SPEC_VERSION - 1);
    snprintf(frame, sizeof frame, "{\"type\":\"utterance.open\",\"utterance\":%s}", bad);
    fio_push(&r.io, frame);
    (void) transport_step(&r.tr, 0);
    CHECK_EQ(r.io.nsent, 2, "hello + one nack");
    cJSON *n = sent(&r, 1);
    CHECK_STR(jstr(n, "type"), "nack", "nack type");
    CHECK_STR(jstr(n, "id"), "spec-old-000001", "nack id");
    CHECK_STR(jstr(n, "reason"), "spec_mismatch", "nack reason spec_mismatch");
    cJSON_Delete(n);
    CHECK_EQ(band_queue_count(&r.q), 0, "nothing held");

    /* queue_full: 20 pending openers (advance: tap so none plays), the 21st is nacked */
    trig r2;
    trig_init(&r2, "band-test-key-0123456789");
    fio_push(&r2.io, "{\"type\":\"hello.ack\",\"v\":1,\"wearer\":\"w_1\",\"device\":\"d_1\",\"spec_version\":4,\"prefs\":{\"advance\":\"tap\"}}");
    static char frames[BAND_QUEUE_CAP + 1][256];
    for (int i = 0; i <= BAND_QUEUE_CAP; i++) {
        snprintf(frames[i], sizeof frames[i], "{\"type\":\"utterance.open\",\"utterance\":{\"id\":\"full-%04d-xxxx\",\"kind\":\"message\",\"words\":[\"a\"],\"spec_version\":%d}}", i, HAPTIC_SPEC_VERSION);
        fio_push(&r2.io, frames[i]);
    }
    (void) transport_step(&r2.tr, 0);
    CHECK(!r2.tr.advance_auto, "advance tap applied");
    CHECK_EQ(band_queue_count(&r2.q), BAND_QUEUE_CAP, "queue at the cap");
    CHECK(!turn_is_loaded(&r2.t), "tap mode: nothing loads without a tap");
    CHECK_EQ(r2.io.nsent, 2, "hello + queue_full nack");
    n = sent(&r2, 1);
    CHECK_STR(jstr(n, "type"), "nack", "nack type");
    CHECK_STR(jstr(n, "id"), "full-0020-xxxx", "the 21st is nacked");
    CHECK_STR(jstr(n, "reason"), "queue_full", "reason queue_full");
    cJSON_Delete(n);
    /* the tap releases the head; the control frame goes out */
    (void) transport_control(&r2.tr, TURN_CTL_ADVANCE, 0);
    (void) transport_step(&r2.tr, 0);
    CHECK(turn_is_loaded(&r2.t), "tap loads the head");
    n = sent(&r2, 2);
    CHECK_STR(jstr(n, "type"), "control", "control frame");
    CHECK_STR(jstr(n, "action"), "advance", "control action advance");
    cJSON_Delete(n);
    /* cancel of a queued one removes it; cancel of the current releases it silently */
    fio_push(&r2.io, "{\"type\":\"utterance.cancel\",\"id\":\"full-0005-xxxx\",\"reason\":\"cancelled_by_sender\"}");
    fio_push(&r2.io, "{\"type\":\"utterance.cancel\",\"id\":\"full-0000-xxxx\",\"reason\":\"failover\"}");
    int before = r2.io.nsent;
    (void) transport_step(&r2.tr, 1);
    CHECK(!band_queue_holds(&r2.q, "full-0005-xxxx"), "queued one cancelled");
    CHECK(!band_queue_holds(&r2.q, "full-0000-xxxx"), "current one cancelled");
    CHECK(!turn_is_loaded(&r2.t) || strcmp(turn_current(&r2.t)->id, "full-0000-xxxx") != 0, "the cancelled current is released");
    CHECK_EQ(band_queue_count(&r2.q), BAND_QUEUE_CAP - 2, "two removed");
    /* a cancel sends nothing but the progress of whatever played */
    for (int i = before; i < r2.io.nsent; i++) { cJSON *f = sent(&r2, i); CHECK(strcmp(jstr(f, "type"), "nack") != 0, "no nack for a relay cancel"); cJSON_Delete(f); }

    /* body timeout → nack body_timeout; the relay's error body → no nack */
    trig r3;
    trig_init(&r3, "band-test-key-0123456789");
    fio_push(&r3.io, k_ack);
    snprintf(frame, sizeof frame, "{\"type\":\"utterance.open\",\"utterance\":%s}", k_pending);
    fio_push(&r3.io, frame);
    uint32_t now = twalk(&r3, 0, 120000);
    (void) now;
    int nack_i = -1;
    for (int i = 0; i < r3.io.nsent; i++) { cJSON *f = sent(&r3, i); if (strcmp(jstr(f, "type"), "nack") == 0) { nack_i = i; CHECK_STR(jstr(f, "reason"), "body_timeout", "body timeout nack"); CHECK_STR(jstr(f, "id"), "golden-pending-rem", "body timeout nack id"); } cJSON_Delete(f); }
    CHECK(nack_i > 0, "a body_timeout nack went out");
    CHECK_EQ(band_queue_count(&r3.q), 0, "the timed-out utterance is dropped");
    cJSON *wk = sent(&r3, 2);
    CHECK_STR(jstr(wk, "phase"), "working", "progress working was reported");
    cJSON_Delete(wk);

    trig r4;
    trig_init(&r4, "band-test-key-0123456789");
    fio_push(&r4.io, k_ack);
    fio_push(&r4.io, frame);
    (void) transport_step(&r4.tr, 0);
    fio_push(&r4.io, "{\"type\":\"utterance.body\",\"id\":\"golden-pending-rem\",\"error\":\"compose_failed\"}");
    (void) twalk(&r4, 0, 120000);
    for (int i = 0; i < r4.io.nsent; i++) { cJSON *f = sent(&r4, i); CHECK(strcmp(jstr(f, "type"), "nack") != 0, "no nack for the relay's own error body"); cJSON_Delete(f); }
    CHECK_EQ(turn_last_result(&r4.t), TURN_RESULT_BODY_ERROR, "error body result");
    CHECK_EQ(band_queue_count(&r4.q), 0, "the failed utterance is dropped");

    /* a body with words for the current utterance plays them */
    trig r5;
    trig_init(&r5, "band-test-key-0123456789");
    fio_push(&r5.io, k_ack);
    fio_push(&r5.io, frame);
    (void) transport_step(&r5.tr, 0);
    fio_push(&r5.io, "{\"type\":\"utterance.body\",\"id\":\"golden-pending-rem\",\"words\":[\"meds\",\"nine\"],\"source\":\"live\"}");
    (void) twalk(&r5, 0, 120000);
    int got_word1 = 0, got_played = 0;
    for (int i = 0; i < r5.io.nsent; i++) {
        cJSON *f = sent(&r5, i);
        if (strcmp(jstr(f, "type"), "progress") == 0 && strcmp(jstr(f, "phase"), "word") == 0 && jnum(f, "word_index") == 1) { got_word1 = 1; }
        if (strcmp(jstr(f, "type"), "played") == 0) { got_played = 1; }
        cJSON_Delete(f);
    }
    CHECK(got_word1 && got_played, "the late body's words played and the utterance was acknowledged");
    /* a body for a QUEUED utterance completes it in the queue */
    trig r6;
    trig_init(&r6, "band-test-key-0123456789");
    fio_push(&r6.io, "{\"type\":\"hello.ack\",\"v\":1,\"wearer\":\"w_1\",\"device\":\"d_1\",\"spec_version\":4,\"prefs\":{\"advance\":\"tap\"}}");
    fio_push(&r6.io, frame);
    fio_push(&r6.io, "{\"type\":\"utterance.body\",\"id\":\"golden-pending-rem\",\"words\":[\"late\"]}");
    (void) transport_step(&r6.tr, 0);
    const ziv_utterance *held_u = band_queue_find(&r6.q, "golden-pending-rem");
    CHECK(held_u && !held_u->body_pending && held_u->word_count == 1, "queued utterance completed by its body");
}

static void test_transport_reconnect_and_liveness(void)
{
    /* backoff: grows by doubling with jitter in [d/2, d], capped */
    trig r;
    trig_init(&r, "band-test-key-0123456789");
    r.io.connect_rc = -1;
    uint32_t now = 0;
    uint32_t base = WORKING_EVERY_MS;
    uint32_t prev_hi = 0;
    for (int attempt = 0; attempt < TRANSPORT_BACKOFF_STEPS + 3; attempt++) {
        uint32_t next = transport_step(&r.tr, now);
        CHECK_EQ(r.io.connects, attempt + 1, "a connect attempt per due step");
        CHECK_EQ(transport_state(&r.tr), TRANSPORT_OFFLINE, "offline while connects fail");
        uint32_t steps = (uint32_t) attempt + 1 < TRANSPORT_BACKOFF_STEPS ? (uint32_t) attempt + 1 : TRANSPORT_BACKOFF_STEPS;
        uint32_t d = base << steps;
        uint32_t delay = next - now;
        char m[96];
        snprintf(m, sizeof m, "attempt %d delay %u within [%u, %u]", attempt, (unsigned) delay, (unsigned) (d / 2), (unsigned) d);
        CHECK(delay >= d / 2 && delay <= d, m);
        if (attempt >= TRANSPORT_BACKOFF_STEPS) { CHECK(d == (base << TRANSPORT_BACKOFF_STEPS), "backoff holds at the cap"); }
        prev_hi = d;
        now = next;
    }
    (void) prev_hi;
    /* a connect succeeds: hello goes out with last_acked + held (resume) */
    r.io.connect_rc = 0;
    ziv_utterance u;
    make_utt(&u, "held-while-off-01", "ok");
    band_queue_push(&r.q, &u);
    band_queue_set_last_acked(&r.q, "acked-before-0001");
    int sent_before_hello = r.io.nsent;
    (void) transport_step(&r.tr, now);
    CHECK_EQ(transport_state(&r.tr), TRANSPORT_HELLO_SENT, "hello sent after reconnect");
    cJSON *hello = sent(&r, sent_before_hello);   /* the first frame of the new link */
    CHECK_STR(jstr(hello, "last_acked"), "acked-before-0001", "hello resumes with last_acked");
    cJSON *held = cJSON_GetObjectItemCaseSensitive(hello, "held");
    CHECK(cJSON_IsArray(held) && cJSON_GetArraySize(held) == 1 && strcmp(cJSON_GetArrayItem(held, 0)->valuestring, "held-while-off-01") == 0, "hello lists the held ids");
    cJSON_Delete(hello);
    fio_push(&r.io, k_ack);
    (void) transport_step(&r.tr, now);
    CHECK_EQ(transport_state(&r.tr), TRANSPORT_READY, "ready");
    CHECK_EQ(r.tr.attempts, 0, "attempts reset by the ack");

    /* the link drops (-1 from recv): offline, a reconnect scheduled, playback continues offline */
    fio_push(&r.io, NULL);
    (void) transport_step(&r.tr, now);
    CHECK_EQ(transport_state(&r.tr), TRANSPORT_OFFLINE, "offline after the drop");
    CHECK_EQ(r.io.closes, 1, "adapter closed");
    CHECK(r.tr.next_connect_ms > now, "reconnect scheduled");
    int sent_before = r.io.nsent;
    uint32_t reconnect_at = r.tr.next_connect_ms;
    (void) twalk(&r, now, reconnect_at - 1);
    CHECK(r.tr.n.played >= 1 || band_queue_count(&r.q) == 0 || turn_is_loaded(&r.t), "the held utterance plays while offline");
    CHECK(r.tr.n.frames_dropped > 0, "frames while offline are dropped and counted");
    CHECK_EQ(r.io.nsent, sent_before, "nothing reaches a closed adapter");

    /* liveness: a ping each period; an unanswered ping drops the link */
    trig r2;
    trig_init_pings(&r2, "band-test-key-0123456789", 0);   /* 0 = the default cadence */
    fio_push(&r2.io, k_ack);
    (void) transport_step(&r2.tr, 0);
    uint32_t ping_every = TRANSPORT_PING_REPEATS * WORKING_EVERY_MS;
    uint32_t next = transport_step(&r2.tr, 1);
    CHECK_EQ(next, ping_every, "idle: the next deadline is the ping");
    (void) transport_step(&r2.tr, ping_every);
    cJSON *ping = sent(&r2, r2.io.nsent - 1);
    CHECK_STR(jstr(ping, "type"), "ping", "ping sent on time");
    cJSON_Delete(ping);
    fio_push(&r2.io, "{\"type\":\"pong\"}");
    (void) transport_step(&r2.tr, ping_every + 1);
    CHECK(!r2.tr.pong_due, "pong clears the debt");
    (void) transport_step(&r2.tr, 2 * ping_every);
    CHECK(r2.tr.pong_due, "second ping outstanding");
    (void) transport_step(&r2.tr, 3 * ping_every);
    CHECK_EQ(transport_state(&r2.tr), TRANSPORT_OFFLINE, "an unanswered ping drops the link");

    /* pref.set applies; the wearer's pace change sends pref.changed; input.text shape */
    trig r3;
    trig_init(&r3, "band-test-key-0123456789");
    fio_push(&r3.io, k_ack);
    fio_push(&r3.io, "{\"type\":\"pref.set\",\"prefs\":{\"pace_ms\":500}}");
    (void) transport_step(&r3.tr, 0);
    CHECK_EQ(turn_pace(&r3.t), 500, "pref.set pace applied");
    CHECK_EQ(transport_set_pace(&r3.tr, 350), 350, "wearer pace set");
    cJSON *pc = sent(&r3, r3.io.nsent - 1);
    CHECK_STR(jstr(pc, "type"), "pref.changed", "pref.changed sent");
    cJSON *prefs = cJSON_GetObjectItemCaseSensitive(pc, "prefs");
    CHECK_EQ(jnum(prefs, "pace_ms"), 350, "pref.changed carries the pace");
    cJSON_Delete(pc);
    const char *ws[2] = { "yes", "please" };
    CHECK_EQ(transport_send_input_text(&r3.tr, ws, 2, "golden-message-two-words"), 0, "input.text sent");
    cJSON *it = sent(&r3, r3.io.nsent - 1);
    CHECK_STR(jstr(it, "type"), "input.text", "input.text type");
    cJSON *words = cJSON_GetObjectItemCaseSensitive(it, "words");
    CHECK(cJSON_IsArray(words) && cJSON_GetArraySize(words) == 2 && strcmp(cJSON_GetArrayItem(words, 1)->valuestring, "please") == 0, "input.text words");
    CHECK_STR(jstr(it, "in_reply_to"), "golden-message-two-words", "input.text in_reply_to");
    cJSON_Delete(it);
    CHECK_EQ(transport_send_input_text(&r3.tr, ws, 0, NULL), -1, "empty input.text refused");
    /* a malformed frame is counted, not fatal */
    fio_push(&r3.io, "{\"type\":\"mystery\"}");
    fio_push(&r3.io, "not json at all");
    uint32_t bad_before = r3.tr.n.bad_frames;
    (void) transport_step(&r3.tr, 1);
    CHECK_EQ(r3.tr.n.bad_frames, bad_before + 2, "unknown and unparsable frames counted");
    CHECK_EQ(transport_state(&r3.tr), TRANSPORT_READY, "still ready after bad frames");
}

int main(void)
{
    test_decoder();
    test_queue();
    test_turn_six_actuator_two_words();
    test_turn_single_actuator_hello();
    test_turn_single_actuator_leading_silence_segment();
    test_turn_body_pending();
    test_turn_controls();
    test_turn_beats_equal_word_play();
    test_transport_hello_and_play();
    test_transport_nacks_and_cancel();
    test_transport_reconnect_and_liveness();
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
