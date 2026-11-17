/* Exercise the actual channel handlers and pointer decoder without a remote login. */
#include "../src/remote_manager/protocols/native/rdp.c"
#include <assert.h>
static unsigned offers, requests, response_flags, response_length, callback_length;
static int cursor_kind;
static BYTE response_bytes[128];
static UINT ok_caps(CliprdrClientContext* c, const CLIPRDR_CAPABILITIES* caps) { return 0; }
static UINT format_list(CliprdrClientContext* c, const CLIPRDR_FORMAT_LIST* list) {
    assert(list->numFormats == 1 && list->formats[0].formatId == CF_UNICODETEXT);
    offers++; return 0;
}
static UINT list_response(CliprdrClientContext* c, const CLIPRDR_FORMAT_LIST_RESPONSE* r) {
    assert(r->common.msgFlags == CB_RESPONSE_OK); return 0;
}
static UINT data_request(CliprdrClientContext* c, const CLIPRDR_FORMAT_DATA_REQUEST* r) {
    assert(r->requestedFormatId == CF_UNICODETEXT); requests++; return 0;
}
static UINT data_response(CliprdrClientContext* c, const CLIPRDR_FORMAT_DATA_RESPONSE* r) {
    response_flags = r->common.msgFlags; response_length = r->common.dataLen;
    if (response_length) memcpy(response_bytes, r->requestedFormatData, response_length);
    return 0;
}
static void got_clipboard(const BYTE* data, int length) { callback_length = length; }
static void got_pointer(const BYTE* data, int width, int height, int x, int y) {
    cursor_kind = width;
    if (width > 0) {
        assert(width == 2 && height == 2 && x == 1 && y == 1);
        assert(data[0] == 30 && data[1] == 20 && data[2] == 10 && data[3] == 255);
    }
}
static void got_frame(const BYTE* data, int width, int height, int stride) { }
static int cert_answer;
static int got_cert(const char* host, const char* subject, const char* fingerprint, int changed) {
    return cert_answer;
}
static UINT layouts;
static UINT layout(DispClientContext* disp, UINT32 count, DISPLAY_CONTROL_MONITOR_LAYOUT* m) {
    assert(count == 1 && m->Width == 1024 && m->Height == 768);
    layouts++; return CHANNEL_RC_OK;
}
int main(void) {
    freerdp* f = urdp_new("localhost", 3389, "test", "", "", 800, 600, got_frame, got_cert);
    assert(f);
    urdp_callbacks(f, got_pointer, got_clipboard);
    Context* c = (Context*)f->context;
    assert(urdp_configure(f, 7, 32, 15, 128, 1));
    assert(freerdp_settings_get_bool(c->base.settings, FreeRDP_RedirectClipboard));
    assert(freerdp_settings_get_uint32(c->base.settings, FreeRDP_ClipboardFeatureMask) == 0x11);
    assert(!freerdp_settings_get_bool(c->base.settings, FreeRDP_IgnoreCertificate));
    assert(!freerdp_settings_get_bool(c->base.settings, FreeRDP_RedirectDrives));
    assert(pre(f));
    assert(f->LoadChannels);
    assert(f->LoadChannels(f));
    assert(freerdp_static_channel_collection_find(f->context->settings, "cliprdr"));
    CliprdrClientContext clip = { .ClientCapabilities = ok_caps, .ClientFormatList = format_list,
        .ClientFormatListResponse = list_response, .ClientFormatDataRequest = data_request,
        .ClientFormatDataResponse = data_response };
    clipboard_connected(c, &clip);
    const BYTE text[] = { 'h', 0, 'i', 0, 0, 0 };
    assert(urdp_clipboard(f, text, sizeof(text)));
    assert(!offers);
    assert(clipboard_ready(&clip, NULL) == 0 && offers == 1);
    CLIPRDR_FORMAT_DATA_REQUEST request = { .requestedFormatId = CF_UNICODETEXT };
    clipboard_data_request(&clip, &request);
    assert(response_flags == CB_RESPONSE_OK && response_length == sizeof(text));
    assert(memcmp(response_bytes, text, sizeof(text)) == 0);
    request.requestedFormatId = CF_TEXT;
    clipboard_data_request(&clip, &request);
    assert(response_flags == CB_RESPONSE_FAIL && response_length == 0);
    assert(!urdp_clipboard(f, text, CLIP_LIMIT+2));
    assert(!urdp_clipboard(f, text, 3));
    CLIPRDR_FORMAT fmt = { .formatId = CF_UNICODETEXT };
    CLIPRDR_FORMAT_LIST formats = { .numFormats = 1, .formats = &fmt };
    clipboard_formats(&clip, &formats);
    assert(callback_length == (unsigned)-1);
    assert(urdp_clipboard_request(f) && requests == 1);
    assert(urdp_clipboard_request(f) && requests == 1); /* only one outstanding request */
    CLIPRDR_FORMAT_DATA_RESPONSE data = { .common.msgFlags = CB_RESPONSE_OK,
        .common.dataLen = sizeof(text), .requestedFormatData = text };
    clipboard_data_response(&clip, &data);
    assert(callback_length == sizeof(text));
    clipboard_formats(&clip, &formats);
    urdp_clipboard_request(f);
    urdp_clipboard(f, text, sizeof(text)); /* local copy invalidates old remote data */
    callback_length = 0;
    clipboard_data_response(&clip, &data);
    assert(callback_length == (unsigned)-1);
    callback_length = 0;
    clipboard_formats(&clip, &formats);
    urdp_clipboard_request(f);
    callback_length = 0;
    data.common.dataLen = CLIP_LIMIT+2;
    clipboard_data_response(&clip, &data);
    assert(callback_length == 0);
    /* Default reject, explicit session-only acceptance, changed-cert callback. */
    cert_answer = 0;
    assert(cert(f, "localhost", 3389, "", "", "", "", 0) == 0);
    cert_answer = 1;
    assert(cert(f, "localhost", 3389, "", "", "", "", 0) == 2);
    assert(changed(f, "localhost", 3389, "", "", "", "", "", "", "", 0) == 2);
    rdpGdi palette_context = { 0 };
    f->context->gdi = &palette_context;
    BYTE pixels[16] = {10,20,30,255,10,20,30,255,10,20,30,255,10,20,30,255};
    BYTE mask[4] = {0};
    Pointer p = { .base.width=2, .base.height=2, .base.xPos=1, .base.yPos=1,
        .base.xorBpp=32, .base.lengthXorMask=16, .base.lengthAndMask=4,
        .base.xorMaskData=pixels, .base.andMaskData=mask };
    assert(pointer_new(f->context, &p.base));
    assert(pointer_set(f->context, &p.base) && cursor_kind == 2);
    pointer_free(f->context, &p.base);
    assert(pointer_null(f->context) && cursor_kind == -1);
    assert(pointer_default(f->context) && cursor_kind == 0);
    DispClientContext disp = { .custom = c, .SendMonitorLayout = layout };
    c->disp = &disp;
    assert(urdp_resize(f, 1025, 768));
    send_layout(c); assert(!layouts); /* wait for the actual server capability */
    display_caps(&disp, 1, 8192, 8192);
    send_layout(c); assert(layouts == 1);
    send_layout(c); assert(layouts == 1); /* no duplicate requests */
    f->context->gdi = NULL;
    urdp_free(f);
    return 0;
}
