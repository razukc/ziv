/*
 * transport.c — the relay protocol on the band (see transport.h).
 *
 * Frame shapes are the schema's (schema/device-frames-up.json and
 * -down.json, generated from ziv/wire.py): every field name and enum value
 * here is spelled as the wire spells it, and the fake relay validates the
 * up frames against the real models in host/fake_relay.py.
 */
#include "transport.h"

#include <stdio.h>
#include <string.h>
#include "cJSON.h"

/* --- small helpers --------------------------------------------------------- */

static void logf_(band_transport *t, const char *what, const char *detail)
{
    if (t->log == NULL) { return; }
    char line[160];
    if (detail && detail[0]) { snprintf(line, sizeof line, "transport: %s %s", what, detail); }
    else { snprintf(line, sizeof line, "transport: %s", what); }
    t->log(t->log_ctx, line);
}

static uint32_t base_ms(const band_transport *t)
{
    return t->cfg.backoff_base_ms ? t->cfg.backoff_base_ms : (uint32_t) WORKING_EVERY_MS;
}

static uint32_t max_ms(const band_transport *t)
{
    return t->cfg.backoff_max_ms ? t->cfg.backoff_max_ms : (base_ms(t) << TRANSPORT_BACKOFF_STEPS);
}

static uint32_t ping_ms(const band_transport *t)
{
    return t->cfg.ping_every_ms ? t->cfg.ping_every_ms : (uint32_t) (TRANSPORT_PING_REPEATS * WORKING_EVERY_MS);
}

/* xorshift32: deterministic jitter given the seed */
static uint32_t rnd(band_transport *t)
{
    uint32_t x = t->rng ? t->rng : 0x9E3779B9u;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    t->rng = x;
    return x;
}

uint32_t transport_backoff_ms(band_transport *t)
{
    /* equal jitter: half the doubled base, plus a random share of the other half */
    uint32_t steps = t->attempts < TRANSPORT_BACKOFF_STEPS ? t->attempts : TRANSPORT_BACKOFF_STEPS;
    uint32_t d = base_ms(t) << steps;
    if (d > max_ms(t)) { d = max_ms(t); }
    uint32_t half = d / 2;
    return half + (half ? rnd(t) % (half + 1) : 0);
}

static void persist(band_transport *t)
{
    if (t->blob == NULL) { return; }
    if (band_queue_save(t->queue, t->blob, t->blob_cap) != BAND_QUEUE_OK) { logf_(t, "persist failed", ""); }
}

/* --- sending --------------------------------------------------------------- */

static int send_json(band_transport *t, cJSON *obj)
{
    char *text = cJSON_PrintUnformatted(obj);
    cJSON_Delete(obj);
    if (text == NULL) { return -1; }
    int rc = -1;
    if (t->connected) {
        rc = t->io->send_frame(t->io->ctx, text, strlen(text));
        if (rc == 0) { t->n.frames_out++; }
    }
    if (rc != 0) { t->n.frames_dropped++; }
    cJSON_free(text);
    return rc;
}

static int send_hello(band_transport *t)
{
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "type", "hello");
    cJSON_AddNumberToObject(o, "v", ZIV_WIRE_VERSION);
    cJSON_AddStringToObject(o, "device_key", t->cfg.device_key ? t->cfg.device_key : "");
    cJSON_AddStringToObject(o, "profile", turn_profile_name(t->cfg.profile));
    cJSON_AddNumberToObject(o, "spec_version", HAPTIC_SPEC_VERSION);
    cJSON_AddNumberToObject(o, "pace_ms", turn_pace(t->turn));
    const char *la = band_queue_last_acked(t->queue);
    if (la[0]) { cJSON_AddStringToObject(o, "last_acked", la); }
    cJSON *held = cJSON_AddArrayToObject(o, "held");
    const char *ids[BAND_QUEUE_CAP];
    uint8_t n = band_queue_ids(t->queue, ids, BAND_QUEUE_CAP);
    for (uint8_t i = 0; i < n; i++) { cJSON_AddItemToArray(held, cJSON_CreateString(ids[i])); }
    return send_json(t, o);
}

static int send_progress(band_transport *t, const char *id, const char *phase, int word_index)
{
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "type", "progress");
    cJSON_AddStringToObject(o, "id", id);
    cJSON_AddStringToObject(o, "phase", phase);
    if (word_index >= 0) { cJSON_AddNumberToObject(o, "word_index", word_index); }
    return send_json(t, o);
}

static int send_played(band_transport *t, const char *id, uint32_t started_ms, uint32_t closed_ms)
{
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "type", "played");
    cJSON_AddStringToObject(o, "id", id);
    cJSON_AddNumberToObject(o, "started_ms", (double) started_ms);
    cJSON_AddNumberToObject(o, "closed_ms", (double) closed_ms);
    t->n.played++;
    return send_json(t, o);
}

static int send_nack(band_transport *t, const char *id, const char *reason)
{
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "type", "nack");
    cJSON_AddStringToObject(o, "id", id);
    cJSON_AddStringToObject(o, "reason", reason);
    t->n.nacks++;
    logf_(t, "nack", reason);
    return send_json(t, o);
}

static int send_ping(band_transport *t)
{
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "type", "ping");
    return send_json(t, o);
}

static const char *control_name(turn_control_t c)
{
    switch (c) {
    case TURN_CTL_STOP:        return "stop";
    case TURN_CTL_REPLAY:      return "replay";
    case TURN_CTL_REPLAY_WORD: return "replay_word";
    case TURN_CTL_SKIP:        return "skip";
    case TURN_CTL_ADVANCE:     return "advance";
    default:                   return "stop";
    }
}

int transport_send_input_text(band_transport *t, const char *const *words, uint8_t n, const char *in_reply_to)
{
    if (words == NULL || n == 0 || n > ZIV_UTT_WORDS_MAX) { return -1; }
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "type", "input.text");
    cJSON *arr = cJSON_AddArrayToObject(o, "words");
    for (uint8_t i = 0; i < n; i++) { cJSON_AddItemToArray(arr, cJSON_CreateString(words[i])); }
    if (in_reply_to && in_reply_to[0]) { cJSON_AddStringToObject(o, "in_reply_to", in_reply_to); }
    return send_json(t, o);
}

uint16_t transport_set_pace(band_transport *t, uint32_t pace_ms)
{
    uint16_t set = turn_set_pace(t->turn, pace_ms);
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "type", "pref.changed");
    cJSON *prefs = cJSON_AddObjectToObject(o, "prefs");
    cJSON_AddNumberToObject(prefs, "pace_ms", set);
    (void) send_json(t, o);
    return set;
}

int transport_control(band_transport *t, turn_control_t action, uint32_t now_ms)
{
    t->now_ms = now_ms;
    if (action == TURN_CTL_ADVANCE) { t->tapped = true; }
    turn_control(t->turn, action, now_ms);
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "type", "control");
    cJSON_AddStringToObject(o, "action", control_name(action));
    return send_json(t, o);
}

/* --- the link ---------------------------------------------------------------- */

static void lost(band_transport *t, uint32_t now_ms)
{
    if (t->connected) { t->io->close(t->io->ctx); }
    t->connected = false;
    t->state = TRANSPORT_OFFLINE;
    t->pong_due = false;
    t->n.disconnects++;
    if (t->attempts < 255) { t->attempts++; }
    t->next_connect_ms = now_ms + transport_backoff_ms(t);
    logf_(t, "link lost; reconnect scheduled", "");
}

void transport_disconnect(band_transport *t, uint32_t now_ms)
{
    lost(t, now_ms);
}

static void try_connect(band_transport *t, uint32_t now_ms)
{
    if (t->io->connect(t->io->ctx) != 0) {
        if (t->attempts < 255) { t->attempts++; }
        t->next_connect_ms = now_ms + transport_backoff_ms(t);
        logf_(t, "connect failed", "");
        return;
    }
    t->connected = true;
    t->n.connects++;
    t->state = TRANSPORT_HELLO_SENT;
    if (send_hello(t) != 0) { lost(t, now_ms); return; }
    logf_(t, "hello sent", "");
}

/* --- inbound frames --------------------------------------------------------- */

static void apply_prefs(band_transport *t, const cJSON *prefs)
{
    if (!cJSON_IsObject(prefs)) { return; }
    const cJSON *pace = cJSON_GetObjectItemCaseSensitive(prefs, "pace_ms");
    if (cJSON_IsNumber(pace)) {
        double v = pace->valuedouble;
        if (v >= 0) { (void) turn_set_pace(t->turn, (uint32_t) v); }
    }
    const cJSON *adv = cJSON_GetObjectItemCaseSensitive(prefs, "advance");
    if (cJSON_IsString(adv) && adv->valuestring) {
        if (strcmp(adv->valuestring, "auto") == 0) { t->advance_auto = true; }
        else if (strcmp(adv->valuestring, "tap") == 0) { t->advance_auto = false; }
    }
}

static const char *nack_reason_for(ziv_utt_err err)
{
    switch (err) {
    case ZIV_UTT_ERR_SPEC_VERSION: return "spec_mismatch";
    case ZIV_UTT_ERR_LETTERS:      return "unencodable";
    case ZIV_UTT_ERR_OVER_CAP:     return "over_budget";
    default:                       return "bad_request";
    }
}

/* An utterance object from utterance.open or hello.ack.resend. */
static void open_utterance(band_transport *t, const cJSON *obj)
{
    ziv_utt_err err = utterance_decode_object(obj, &t->scratch);
    if (err != ZIV_UTT_OK) {
        t->n.bad_frames++;
        const cJSON *id = cJSON_IsObject(obj) ? cJSON_GetObjectItemCaseSensitive(obj, "id") : NULL;
        if (cJSON_IsString(id) && id->valuestring && utterance_valid_id(id->valuestring)) {
            (void) send_nack(t, id->valuestring, nack_reason_for(err));
        } else {
            logf_(t, "utterance refused without an id", utterance_err_name(err));
        }
        return;
    }
    band_queue_err qe = band_queue_push(t->queue, &t->scratch);
    if (qe == BAND_QUEUE_FULL) { (void) send_nack(t, t->scratch.id, "queue_full"); return; }
    if (qe == BAND_QUEUE_DUPLICATE) { logf_(t, "duplicate ignored", ""); return; }
    persist(t);
    /* announce, then wait (plan §4 invariant 4): its cue now, its turn later */
    if (turn_is_active(t->turn)) { turn_announce(t->turn, t->scratch.kind); }
}

static void handle_body(band_transport *t, const cJSON *frame)
{
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(frame, "id");
    if (!cJSON_IsString(id) || id->valuestring == NULL) { t->n.bad_frames++; return; }
    const cJSON *error = cJSON_GetObjectItemCaseSensitive(frame, "error");
    const cJSON *words = cJSON_GetObjectItemCaseSensitive(frame, "words");
    bool failed = cJSON_IsString(error) && error->valuestring != NULL;

    const ziv_utterance *cur = turn_current(t->turn);
    bool is_current = cur != NULL && strcmp(cur->id, id->valuestring) == 0;
    ziv_utterance *held = band_queue_find(t->queue, id->valuestring);
    if (held == NULL && !is_current) { logf_(t, "body for an unknown id", ""); return; }

    if (failed) {
        if (held) { held->body_error = true; }
        if (is_current) { turn_set_body_error(t->turn); }
        persist(t);
        return;
    }
    if (!cJSON_IsArray(words)) { t->n.bad_frames++; return; }
    /* decode once into the scratch to validate, then apply */
    ziv_utterance probe;
    utterance_clear(&probe);
    ziv_utt_err err = utterance_decode_words(words, &probe);
    if (err != ZIV_UTT_OK) { (void) send_nack(t, id->valuestring, nack_reason_for(err)); return; }
    if (held) {
        (void) utterance_decode_words(words, held);
        held->body_pending = false;
        held->body_error = false;
    }
    if (is_current) {
        const char *ws[ZIV_UTT_WORDS_MAX];
        char text[ZIV_UTT_WORDS_MAX][ZIV_UTT_WORD_MAX + 1];
        for (uint8_t i = 0; i < probe.word_count; i++) {
            (void) utterance_word_text(&probe, i, text[i], sizeof text[i]);
            ws[i] = text[i];
        }
        (void) turn_set_body(t->turn, ws, probe.word_count);
    }
    persist(t);
}

static void handle_cancel(band_transport *t, const cJSON *frame)
{
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(frame, "id");
    if (!cJSON_IsString(id) || id->valuestring == NULL) { t->n.bad_frames++; return; }
    const ziv_utterance *cur = turn_current(t->turn);
    if (cur != NULL && strcmp(cur->id, id->valuestring) == 0) {
        turn_release(t->turn);   /* silent; the relay knows why */
        logf_(t, "current utterance cancelled by the relay", "");
    }
    (void) band_queue_cancel(t->queue, id->valuestring);
    persist(t);
}

static void handle_hello_ack(band_transport *t, const cJSON *frame, uint32_t now_ms)
{
    const cJSON *w = cJSON_GetObjectItemCaseSensitive(frame, "wearer");
    const cJSON *d = cJSON_GetObjectItemCaseSensitive(frame, "device");
    const cJSON *sv = cJSON_GetObjectItemCaseSensitive(frame, "spec_version");
    if (cJSON_IsString(w) && w->valuestring) { strncpy(t->wearer, w->valuestring, ZIV_UTT_ID_MAX); t->wearer[ZIV_UTT_ID_MAX] = '\0'; }
    if (cJSON_IsString(d) && d->valuestring) { strncpy(t->device, d->valuestring, ZIV_UTT_ID_MAX); t->device[ZIV_UTT_ID_MAX] = '\0'; }
    if (cJSON_IsNumber(sv)) {
        t->relay_spec_version = (int) sv->valuedouble;
        if (t->relay_spec_version != HAPTIC_SPEC_VERSION) { logf_(t, "relay spec version differs", ""); }
    }
    apply_prefs(t, cJSON_GetObjectItemCaseSensitive(frame, "prefs"));
    const cJSON *resend = cJSON_GetObjectItemCaseSensitive(frame, "resend");
    if (cJSON_IsArray(resend)) {
        const cJSON *u = NULL;
        cJSON_ArrayForEach(u, resend) { open_utterance(t, u); }
    }
    t->state = TRANSPORT_READY;
    t->attempts = 0;
    t->pong_due = false;
    t->next_ping_ms = now_ms + ping_ms(t);
    logf_(t, "ready", "");
}

int transport_handle_frame(band_transport *t, const char *text, size_t len, uint32_t now_ms)
{
    t->now_ms = now_ms;
    t->n.frames_in++;
    cJSON *frame = cJSON_ParseWithLength(text, len);
    if (frame == NULL || !cJSON_IsObject(frame)) { cJSON_Delete(frame); t->n.bad_frames++; return -1; }
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(frame, "type");
    if (!cJSON_IsString(type) || type->valuestring == NULL) { cJSON_Delete(frame); t->n.bad_frames++; return -1; }
    const char *ty = type->valuestring;
    int rc = 0;

    if (strcmp(ty, "hello.ack") == 0) {
        handle_hello_ack(t, frame, now_ms);
    } else if (strcmp(ty, "utterance.open") == 0) {
        open_utterance(t, cJSON_GetObjectItemCaseSensitive(frame, "utterance"));
    } else if (strcmp(ty, "utterance.body") == 0) {
        handle_body(t, frame);
    } else if (strcmp(ty, "utterance.cancel") == 0) {
        handle_cancel(t, frame);
    } else if (strcmp(ty, "pref.set") == 0) {
        apply_prefs(t, cJSON_GetObjectItemCaseSensitive(frame, "prefs"));
    } else if (strcmp(ty, "pong") == 0) {
        t->pong_due = false;
        t->n.pongs++;
    } else if (strcmp(ty, "error") == 0) {
        const cJSON *reason = cJSON_GetObjectItemCaseSensitive(frame, "reason");
        logf_(t, "relay error", cJSON_IsString(reason) ? reason->valuestring : "");
        t->n.bad_frames++;
    } else {
        t->n.bad_frames++;
        rc = -1;
    }
    cJSON_Delete(frame);
    return rc;
}

/* --- the turn's events → frames --------------------------------------------- */

static void on_turn_event(void *ctx, turn_phase phase, int word_index, const char *label)
{
    band_transport *t = (band_transport *) ctx;
    const ziv_utterance *cur = turn_current(t->turn);
    if (cur == NULL) { return; }
    char id[ZIV_UTT_ID_MAX + 1];
    strncpy(id, cur->id, ZIV_UTT_ID_MAX);
    id[ZIV_UTT_ID_MAX] = '\0';
    (void) label;

    switch (phase) {
    case TURN_PHASE_CUE:     (void) send_progress(t, id, "cue", -1); break;
    case TURN_PHASE_WORKING: (void) send_progress(t, id, "working", -1); break;
    case TURN_PHASE_WORD:    (void) send_progress(t, id, "word", word_index); break;
    case TURN_PHASE_CLOSE:   (void) send_progress(t, id, "close", -1); break;
    case TURN_PHASE_DONE: {
        (void) send_played(t, id, turn_started_ms(t->turn), turn_closed_ms(t->turn));
        const ziv_utterance *head = band_queue_peek(t->queue);
        if (head && strcmp(head->id, id) == 0) { (void) band_queue_ack(t->queue); }
        else { (void) band_queue_cancel(t->queue, id); band_queue_set_last_acked(t->queue, id); }
        persist(t);
        turn_release(t->turn);
        break;
    }
    case TURN_PHASE_FAILED: {
        turn_result r = turn_last_result(t->turn);
        if (r != TURN_RESULT_BODY_ERROR) {   /* the relay already knows about its own error body */
            (void) send_nack(t, id, turn_result_name(r));
        }
        (void) band_queue_cancel(t->queue, id);
        persist(t);
        turn_release(t->turn);
        break;
    }
    default:
        break;
    }
}

/* --- init / step ------------------------------------------------------------ */

void transport_init(band_transport *t, band_frame_io *io, band_queue *q, turn *tn, const band_transport_config *cfg)
{
    memset(t, 0, sizeof *t);
    t->io = io;
    t->queue = q;
    t->turn = tn;
    t->cfg = *cfg;
    t->rng = cfg->seed ? cfg->seed : 0x2545F491u;
    t->advance_auto = true;
    t->relay_spec_version = -1;
    t->state = TRANSPORT_OFFLINE;
    t->next_connect_ms = 0;   /* the first step connects */
    /* the turn's phase events become frames; its beat callback stays the app's */
    turn_set_callbacks(tn, on_turn_event, t, tn->on_beat, tn->beat_ctx);
}

void transport_set_log(band_transport *t, band_log_cb cb, void *ctx) { t->log = cb; t->log_ctx = ctx; }
void transport_set_blob(band_transport *t, uint8_t *blob, size_t cap) { t->blob = blob; t->blob_cap = cap; }

static uint32_t sooner(uint32_t a, uint32_t b)
{
    if (a == 0) { return b; }
    if (b == 0) { return a; }
    return a < b ? a : b;
}

static void pump_inbound(band_transport *t, uint32_t now_ms)
{
    for (int guard = 0; t->connected && guard < 64; guard++) {
        int n = t->io->recv_frame(t->io->ctx, t->rx, sizeof t->rx, 0);
        if (n == 0) { return; }
        if (n < 0) { lost(t, now_ms); return; }
        (void) transport_handle_frame(t, t->rx, (size_t) n, now_ms);
    }
}

static void hand_off(band_transport *t, uint32_t now_ms)
{
    if (turn_is_loaded(t->turn)) { return; }
    const ziv_utterance *head = band_queue_peek(t->queue);
    if (head == NULL) { return; }
    if (!t->advance_auto && !t->tapped) { return; }   /* the wearer releases the queue */
    t->tapped = false;
    if (turn_load(t->turn, head)) { logf_(t, "playing", ""); }
    (void) now_ms;
}

uint32_t transport_step(band_transport *t, uint32_t now_ms)
{
    t->now_ms = now_ms;
    uint32_t deadline = 0;

    /* the link */
    if (!t->connected) {
        if (now_ms >= t->next_connect_ms) { try_connect(t, now_ms); }
        if (!t->connected) { deadline = sooner(deadline, t->next_connect_ms); }
    }
    pump_inbound(t, now_ms);

    /* liveness */
    if (t->connected && t->state == TRANSPORT_READY) {
        if (now_ms >= t->next_ping_ms) {
            if (t->pong_due) {
                lost(t, now_ms);
            } else {
                (void) send_ping(t);
                t->pong_due = true;
                t->next_ping_ms = now_ms + ping_ms(t);
            }
        }
        if (t->connected) { deadline = sooner(deadline, t->next_ping_ms); }
        else { deadline = sooner(deadline, t->next_connect_ms); }
    }

    /* the haptics: the turn, then the queue hand-off */
    for (int guard = 0; guard < 4; guard++) {
        uint32_t next = turn_step(t->turn, now_ms);
        if (next != 0) { deadline = sooner(deadline, next); break; }
        bool was_loaded = turn_is_loaded(t->turn);
        hand_off(t, now_ms);
        if (!turn_is_loaded(t->turn) || was_loaded) { break; }
    }
    return deadline;
}

int transport_wait(band_transport *t, uint32_t now_ms, uint32_t timeout_ms)
{
    t->now_ms = now_ms;
    if (!t->connected) { return 0; }
    int n = t->io->recv_frame(t->io->ctx, t->rx, sizeof t->rx, timeout_ms);
    if (n == 0) { return 0; }
    if (n < 0) { lost(t, now_ms); return -1; }
    (void) transport_handle_frame(t, t->rx, (size_t) n, now_ms);
    return 1;
}

band_transport_state transport_state(const band_transport *t) { return t->state; }
const band_transport_counters *transport_counters(const band_transport *t) { return &t->n; }

const char *transport_state_name(band_transport_state s)
{
    switch (s) {
    case TRANSPORT_OFFLINE:    return "offline";
    case TRANSPORT_HELLO_SENT: return "hello_sent";
    case TRANSPORT_READY:      return "ready";
    default:                   return "?";
    }
}
