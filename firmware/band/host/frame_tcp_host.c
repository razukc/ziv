/*
 * frame_tcp_host.c — the host's frame adapter: one JSON frame per line over
 * a TCP client socket (POSIX).  The fake relay (host/fake_relay.py) speaks
 * the same framing.  On the band the same vtable is filled by the
 * esp_websocket_client adapter, where the WebSocket does the framing.
 */
#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE
#include "frame_tcp_host.h"

#include <errno.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

static void drop(frame_tcp_ctx *c)
{
    if (c->fd >= 0) { close(c->fd); }
    c->fd = -1;
    c->inlen = 0;
}

static int tcp_connect(void *vctx)
{
    frame_tcp_ctx *c = (frame_tcp_ctx *) vctx;
    drop(c);
    char port[8];
    snprintf(port, sizeof port, "%u", (unsigned) c->port);
    struct addrinfo hints;
    memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo *res = NULL;
    if (getaddrinfo(c->host, port, &hints, &res) != 0) { return -1; }
    int fd = -1;
    for (struct addrinfo *ai = res; ai != NULL; ai = ai->ai_next) {
        fd = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (fd < 0) { continue; }
        if (connect(fd, ai->ai_addr, ai->ai_addrlen) == 0) { break; }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(res);
    if (fd < 0) { return -1; }
    int one = 1;
    (void) setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    c->fd = fd;
    c->inlen = 0;
    return 0;
}

static int tcp_send(void *vctx, const char *text, size_t len)
{
    frame_tcp_ctx *c = (frame_tcp_ctx *) vctx;
    if (c->fd < 0) { return -1; }
    const char nl = '\n';
    size_t off = 0;
    while (off < len) {
        ssize_t n = write(c->fd, text + off, len - off);
        if (n < 0) { if (errno == EINTR) { continue; } drop(c); return -1; }
        off += (size_t) n;
    }
    while (write(c->fd, &nl, 1) != 1) {
        if (errno != EINTR) { drop(c); return -1; }
    }
    return 0;
}

/* Move one complete line out of inbuf into buf; 1 if there was one. */
static int take_line(frame_tcp_ctx *c, char *buf, size_t cap, int *len_out)
{
    char *nl = memchr(c->inbuf, '\n', c->inlen);
    if (nl == NULL) { return 0; }
    size_t line_len = (size_t) (nl - c->inbuf);
    if (line_len + 1 > cap) { return -1; }   /* does not fit the caller's buffer */
    memcpy(buf, c->inbuf, line_len);
    buf[line_len] = '\0';
    size_t rest = c->inlen - line_len - 1;
    memmove(c->inbuf, nl + 1, rest);
    c->inlen = rest;
    *len_out = (int) line_len;
    return 1;
}

static int tcp_recv(void *vctx, char *buf, size_t cap, uint32_t timeout_ms)
{
    frame_tcp_ctx *c = (frame_tcp_ctx *) vctx;
    if (c->fd < 0) { return -1; }
    int len = 0;
    int have = take_line(c, buf, cap, &len);
    if (have != 0) { if (have < 0) { drop(c); return -1; } return len; }

    for (;;) {
        struct pollfd pfd = { c->fd, POLLIN, 0 };
        int pr = poll(&pfd, 1, (int) timeout_ms);
        if (pr < 0) { if (errno == EINTR) { continue; } drop(c); return -1; }
        if (pr == 0) { return 0; }
        if (c->inlen >= sizeof c->inbuf - 1) { drop(c); return -1; }   /* line too long */
        ssize_t n = read(c->fd, c->inbuf + c->inlen, sizeof c->inbuf - 1 - c->inlen);
        if (n < 0) { if (errno == EINTR) { continue; } drop(c); return -1; }
        if (n == 0) { drop(c); return -1; }   /* EOF */
        c->inlen += (size_t) n;
        have = take_line(c, buf, cap, &len);
        if (have < 0) { drop(c); return -1; }
        if (have > 0) { return len; }
        /* a partial line: only wait again if there is time left */
        if (timeout_ms == 0) { return 0; }
    }
}

static void tcp_close(void *vctx)
{
    drop((frame_tcp_ctx *) vctx);
}

void frame_tcp_io(band_frame_io *io, frame_tcp_ctx *ctx, const char *host, uint16_t port)
{
    ctx->host = host;
    ctx->port = port;
    ctx->fd = -1;
    ctx->inlen = 0;
    io->connect = tcp_connect;
    io->send_frame = tcp_send;
    io->recv_frame = tcp_recv;
    io->close = tcp_close;
    io->ctx = ctx;
}
