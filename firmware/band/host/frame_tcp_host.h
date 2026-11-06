/* frame_tcp_host.h — newline-delimited JSON over TCP: the host's frame adapter. */
#ifndef ZIV_FRAME_TCP_HOST_H
#define ZIV_FRAME_TCP_HOST_H

#include <stdint.h>
#include "transport.h"

typedef struct {
    const char *host;
    uint16_t port;
    int fd;                          /* -1 when closed */
    char inbuf[TRANSPORT_RX_MAX + 1];
    size_t inlen;
} frame_tcp_ctx;

/* Fill io for a client to host:port.  Each frame is one line; a line that
 * does not fit TRANSPORT_RX_MAX is a dropped link, not a truncated frame. */
void frame_tcp_io(band_frame_io *io, frame_tcp_ctx *ctx, const char *host, uint16_t port);

#endif /* ZIV_FRAME_TCP_HOST_H */
