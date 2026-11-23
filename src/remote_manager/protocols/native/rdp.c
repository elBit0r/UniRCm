/* Small FreeRDP 3 ABI bridge. Only the session worker calls this API. */
#include <freerdp/freerdp.h>
#include <freerdp/gdi/gdi.h>
#include <freerdp/gdi/gfx.h>
#include <freerdp/input.h>
#include <freerdp/settings.h>
#include <winpr/synch.h>
#include <winpr/wlog.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <freerdp/client/cmdline.h>
#include <freerdp/client/channels.h>
#include <freerdp/client/disp.h>
#include <freerdp/addin.h>
#include <freerdp/event.h>
#include <freerdp/client/cliprdr.h>
#include <winpr/clipboard.h>

typedef void (*frame_cb)(const BYTE*, int, int, int);
typedef int (*cert_cb)(const char*, const char*, const char*, int);
typedef void (*pointer_cb)(const BYTE*, int, int, int, int);
typedef void (*clipboard_cb)(const BYTE*, int);
typedef struct {
    rdpContext base;
    pointer_cb pointer;
    clipboard_cb clipboard;
    CliprdrClientContext* clip;
    BOOL clip_ready, remote_text, clip_pending;
    unsigned clip_generation, request_generation;
    BYTE* clip_data;
    UINT32 clip_length;
    pthread_mutex_t clip_lock;
    frame_cb frame;
    cert_cb cert;
    DispClientContext* disp;
    atomic_bool graphics_failed;
    BOOL display_ready;
    UINT32 width, height, sent_width, sent_height;
} Context;
#include "pointer.h"
#include "clipboard.h"

static pthread_once_t addins_once = PTHREAD_ONCE_INIT;
static void register_addins(void) {
    freerdp_register_addin_provider(freerdp_channels_load_static_addin_entry, 0);
}
static UINT display_caps(DispClientContext* disp, UINT32 monitors, UINT32 a, UINT32 b) {
    ((Context*)disp->custom)->display_ready = TRUE;
    return CHANNEL_RC_OK;
}
static void channel_connected(void* context, const ChannelConnectedEventArgs* e) {
    Context* c = context;
    if (strcmp(e->name, RDPGFX_DVC_CHANNEL_NAME) == 0) {
        atomic_store(&c->graphics_failed,
                     !c->base.gdi || !gdi_graphics_pipeline_init(c->base.gdi, e->pInterface));
    }
    if (strcmp(e->name, CLIPRDR_SVC_CHANNEL_NAME) == 0) {
        clipboard_connected(c, e->pInterface);
    }
    if (strcmp(e->name, DISP_DVC_CHANNEL_NAME) == 0) {
        c->disp = e->pInterface;
        c->disp->custom = c;
        c->disp->DisplayControlCaps = display_caps;
    }
}
static void channel_disconnected(void* context, const ChannelDisconnectedEventArgs* e) {
    Context* c = context;
    if (strcmp(e->name, RDPGFX_DVC_CHANNEL_NAME) == 0 && c->base.gdi) {
        gdi_graphics_pipeline_uninit(c->base.gdi, e->pInterface);
    }
    if (strcmp(e->name, CLIPRDR_SVC_CHANNEL_NAME) == 0) {
        pthread_mutex_lock(&c->clip_lock);
        c->clip = NULL; c->clip_ready = FALSE; c->clip_pending = FALSE;
        pthread_mutex_unlock(&c->clip_lock);
    }
    if (strcmp(e->name, DISP_DVC_CHANNEL_NAME) == 0) {
        c->disp = NULL;
        c->display_ready = FALSE;
    }
}
static BOOL pre(freerdp* f) {
    rdpContext* c = f->context;
    if (PubSub_SubscribeChannelConnected(c->pubSub, channel_connected) < 0 ||
        PubSub_SubscribeChannelDisconnected(c->pubSub, channel_disconnected) < 0) return FALSE;
    return TRUE;
}
static BOOL load_channels(freerdp* f) {
    /* FreeRDP reloads its channel manager after PreConnect (and gateway policy changes). */
    return freerdp_client_load_addins(f->context->channels, f->context->settings);
}
unsigned urdp_abi_version(void) { return 3; }

static BOOL begin(rdpContext* c) {
    c->gdi->primary->hdc->hwnd->invalid->null = TRUE;
    return TRUE;
}
static BOOL paint(rdpContext* c) {
    Context* ctx = (Context*)c;
    rdpGdi* g = c->gdi;
    ctx->frame(g->primary_buffer, g->width, g->height, g->stride);
    return TRUE;
}
static BOOL resize(rdpContext* c) {
    return gdi_resize(c->gdi, freerdp_settings_get_uint32(c->settings, FreeRDP_DesktopWidth),
                      freerdp_settings_get_uint32(c->settings, FreeRDP_DesktopHeight));
}
static BOOL post(freerdp* f) {
    if (!gdi_init(f, PIXEL_FORMAT_BGRA32)) return FALSE;
    register_pointer(f->context);
    f->context->update->BeginPaint = begin;
    f->context->update->EndPaint = paint;
    f->context->update->DesktopResize = resize;
    return TRUE;
}
static DWORD cert(freerdp* f, const char* host, UINT16 port, const char* cn,
                  const char* subject, const char* issuer, const char* fingerprint, DWORD flags) {
    return ((Context*)f->context)->cert(host, subject, fingerprint, 0) ? 2 : 0;
}
static DWORD changed(freerdp* f, const char* host, UINT16 port, const char* cn,
                     const char* subject, const char* issuer, const char* fingerprint,
                     const char* oldSubject, const char* oldIssuer, const char* oldFingerprint, DWORD flags) {
    return ((Context*)f->context)->cert(host, subject, fingerprint, 1) ? 2 : 0;
}
void* urdp_new(const char* host, unsigned port, const char* user, const char* password,
               const char* domain, unsigned width, unsigned height, frame_cb frame, cert_cb verify) {
    /* No native protocol logs: errors are returned to the GUI without credential data. */
    WLog_SetLogLevel(WLog_GetRoot(), WLOG_OFF);
    freerdp* f = freerdp_new();
    if (!f) return NULL;
    f->ContextSize = sizeof(Context);
    if (!freerdp_context_new(f)) { freerdp_free(f); return NULL; }
    atomic_init(&((Context*)f->context)->graphics_failed, 0);
    pthread_mutex_init(&((Context*)f->context)->clip_lock, NULL);
    ((Context*)f->context)->frame = frame;
    ((Context*)f->context)->cert = verify;
    pthread_once(&addins_once, register_addins);
    f->PreConnect = pre;
    f->LoadChannels = load_channels;
    f->PostConnect = post;
    f->VerifyCertificateEx = cert;
    f->VerifyChangedCertificateEx = changed;
    rdpSettings* s = f->context->settings;
    if (!freerdp_settings_set_string(s, FreeRDP_ServerHostname, host) ||
        !freerdp_settings_set_string(s, FreeRDP_Username, user) ||
        !freerdp_settings_set_string(s, FreeRDP_Password, password) ||
        !freerdp_settings_set_string(s, FreeRDP_Domain, domain) ||
        !freerdp_settings_set_uint32(s, FreeRDP_ServerPort, port) ||
        !freerdp_settings_set_uint32(s, FreeRDP_DesktopWidth, width) ||
        !freerdp_settings_set_uint32(s, FreeRDP_DesktopHeight, height) ||
        !freerdp_settings_set_uint32(s, FreeRDP_ColorDepth, 32) ||
        !freerdp_settings_set_uint32(s, FreeRDP_TcpConnectTimeout, 10000) ||
        !freerdp_settings_set_bool(s, FreeRDP_SoftwareGdi, TRUE) ||
        !freerdp_settings_set_bool(s, FreeRDP_SupportGraphicsPipeline, TRUE)) {
        pthread_mutex_destroy(&((Context*)f->context)->clip_lock);
        freerdp_context_free(f); freerdp_free(f); return NULL;
    }
    return f;
}
int urdp_configure(freerdp* f, unsigned speed, unsigned depth, unsigned timeout,
                   unsigned flags, int automatic) {
    rdpSettings* s = f->context->settings;
    if (!freerdp_set_connection_type(s, speed) ||
        !freerdp_settings_set_uint32(s, FreeRDP_ColorDepth, depth) ||
        !freerdp_settings_set_uint32(s, FreeRDP_TcpConnectTimeout, timeout * 1000) ||
        !freerdp_settings_set_bool(s, FreeRDP_CompressionEnabled, !!(flags & 1)) ||
        !freerdp_settings_set_bool(s, FreeRDP_DisableWallpaper, !(flags & 2)) ||
        !freerdp_settings_set_bool(s, FreeRDP_AllowFontSmoothing, !!(flags & 4)) ||
        !freerdp_settings_set_bool(s, FreeRDP_DisableThemes, !(flags & 8)) ||
        !freerdp_settings_set_bool(s, FreeRDP_DisableFullWindowDrag, !(flags & 16)) ||
        !freerdp_settings_set_bool(s, FreeRDP_DisableMenuAnims, !(flags & 32)) ||
        !freerdp_settings_set_bool(s, FreeRDP_ConsoleSession, !!(flags & 64)) ||
        !freerdp_settings_set_bool(s, FreeRDP_SupportDisplayControl, automatic)) return 0;
    if (!freerdp_settings_set_bool(s, FreeRDP_RedirectClipboard, !!(flags & 128)) ||
        !freerdp_settings_set_uint32(s, FreeRDP_ClipboardFeatureMask,
            CLIPRDR_FLAG_LOCAL_TO_REMOTE | CLIPRDR_FLAG_REMOTE_TO_LOCAL)) return 0;
    /* Clipboard text is opt-in; never redirect other local resources implicitly. */
    const size_t disabled[] = {FreeRDP_RedirectDrives,
        FreeRDP_RedirectPrinters, FreeRDP_RedirectSmartCards, FreeRDP_DeviceRedirection,
        FreeRDP_AudioPlayback, FreeRDP_AudioCapture};
    for (size_t i = 0; i < sizeof(disabled)/sizeof(disabled[0]); i++)
        if (!freerdp_settings_set_bool(s, disabled[i], FALSE)) return 0;
    freerdp_performance_flags_make(s);
    if (automatic) {
        const char* params[] = { "disp" };
        if (!freerdp_client_add_dynamic_channel(s, 1, params)) return 0;
    }
    return 1;
}
int urdp_display_control(freerdp* f) { return ((Context*)f->context)->display_ready; }
int urdp_resize(freerdp* f, unsigned width, unsigned height) {
    Context* c = (Context*)f->context;
    if (width < 320 || width > 8192 || height < 320 || height > 8192) return 0;
    c->width = width - width % 2;
    c->height = height;
    return 1;
}
static BOOL send_layout(Context* c) {
    if (!c->display_ready || !c->disp || !c->width ||
        (c->sent_width == c->width && c->sent_height == c->height)) return TRUE;
    DISPLAY_CONTROL_MONITOR_LAYOUT m = { 0 };
    m.Flags = DISPLAY_CONTROL_MONITOR_PRIMARY;
    m.Width = c->width; m.Height = c->height;
    m.PhysicalWidth = c->width * 254 / 960;
    m.PhysicalHeight = c->height * 254 / 960;
    m.DesktopScaleFactor = m.DeviceScaleFactor = 100;
    if (c->disp->SendMonitorLayout(c->disp, 1, &m) != CHANNEL_RC_OK) {
        c->display_ready = FALSE; /* Preserve the desktop using local scaling. */
        return TRUE;
    }
    c->sent_width = c->width; c->sent_height = c->height;
    return TRUE;
}
int urdp_connect(freerdp* f) { return freerdp_connect(f); }
int urdp_step(freerdp* f) {
    HANDLE events[64];
    if (freerdp_shall_disconnect_context(f->context)) return 0;
    DWORD n = freerdp_get_event_handles(f->context, events, 64);
    if (!n || WaitForMultipleObjects(n, events, FALSE, 20) == WAIT_FAILED) return 0;
    if (!freerdp_check_event_handles(f->context)) return 0;
    Context* c = (Context*)f->context;
    return !atomic_load(&c->graphics_failed) && send_layout(c);
}
unsigned urdp_error(freerdp* f) {
    unsigned error = freerdp_get_last_error(f->context);
    return error ? error : atomic_load(&((Context*)f->context)->graphics_failed);
}
void urdp_abort(freerdp* f) { freerdp_abort_connect_context(f->context); }
void urdp_free(freerdp* f) {
    freerdp_disconnect(f);
    if (f->context->gdi) gdi_free(f);
    PubSub_UnsubscribeChannelConnected(f->context->pubSub, channel_connected);
    PubSub_UnsubscribeChannelDisconnected(f->context->pubSub, channel_disconnected);
    Context* c = (Context*)f->context;
    if (c->clip_data) { memset(c->clip_data, 0, c->clip_length); free(c->clip_data); }
    pthread_mutex_destroy(&c->clip_lock);
    freerdp_context_free(f); freerdp_free(f);
}
int urdp_mouse(freerdp* f, unsigned flags, unsigned x, unsigned y) {
    return freerdp_input_send_mouse_event(f->context->input, flags, x, y);
}
int urdp_key(freerdp* f, unsigned flags, unsigned code, int unicode) {
    if (unicode) return freerdp_input_send_unicode_keyboard_event(f->context->input, flags, code);
    return freerdp_input_send_keyboard_event(f->context->input, flags, code);
}

void urdp_callbacks(freerdp* f, pointer_cb pointer, clipboard_cb clipboard) {
    Context* c = (Context*)f->context;
    c->pointer = pointer; c->clipboard = clipboard;
}

unsigned urdp_clipboard_status(freerdp* f) {
    Context* c = (Context*)f->context;
    pthread_mutex_lock(&c->clip_lock);
    unsigned status = !!c->clip | (c->clip_ready ? 2 : 0) | (c->clip_data ? 4 : 0) | (c->remote_text ? 8 : 0);
    pthread_mutex_unlock(&c->clip_lock);
    return status;
}
