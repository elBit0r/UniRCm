/* Text-only CLIPRDR. No file/image formats, bounded UTF-16 payloads, no logging. */
#define CLIP_LIMIT (1024 * 1024)
static UINT clipboard_offer(Context* c) {
    CLIPRDR_FORMAT format = { .formatId = CF_UNICODETEXT };
    CLIPRDR_FORMAT_LIST list = { .common.msgType = CB_FORMAT_LIST };
    if (!c->clip || !c->clip_ready || !c->clip_data) return CHANNEL_RC_OK;
    list.numFormats = 1; list.formats = &format;
    return c->clip->ClientFormatList(c->clip, &list);
}
static UINT clipboard_ready(CliprdrClientContext* clip, const CLIPRDR_MONITOR_READY* ready) {
    Context* c = clip->custom;
    CLIPRDR_GENERAL_CAPABILITY_SET general = {
        .capabilitySetType = CB_CAPSTYPE_GENERAL, .capabilitySetLength = CB_CAPSTYPE_GENERAL_LEN,
        .version = CB_CAPS_VERSION_2, .generalFlags = CB_USE_LONG_FORMAT_NAMES
    };
    CLIPRDR_CAPABILITIES caps = { .common.msgType = CB_CLIP_CAPS,
        .cCapabilitiesSets = 1, .capabilitySets = (CLIPRDR_CAPABILITY_SET*)&general };
    UINT result = clip->ClientCapabilities(clip, &caps);
    if (result != CHANNEL_RC_OK) return result;
    pthread_mutex_lock(&c->clip_lock);
    c->clip_ready = TRUE;
    result = clipboard_offer(c);
    pthread_mutex_unlock(&c->clip_lock);
    return result;
}
static UINT clipboard_caps(CliprdrClientContext* clip, const CLIPRDR_CAPABILITIES* caps) {
    return CHANNEL_RC_OK;
}
static UINT clipboard_list_response(CliprdrClientContext* clip, const CLIPRDR_FORMAT_LIST_RESPONSE* response) {
    return CHANNEL_RC_OK;
}
static UINT clipboard_formats(CliprdrClientContext* clip, const CLIPRDR_FORMAT_LIST* list) {
    Context* c = clip->custom;
    CLIPRDR_FORMAT_LIST_RESPONSE response = {
        .common.msgType = CB_FORMAT_LIST_RESPONSE, .common.msgFlags = CB_RESPONSE_OK };
    BOOL available = FALSE;
    for (UINT32 i = 0; i < list->numFormats; i++)
        if (list->formats[i].formatId == CF_UNICODETEXT) available = TRUE;
    pthread_mutex_lock(&c->clip_lock);
    c->remote_text = available; c->clip_generation++;
    pthread_mutex_unlock(&c->clip_lock);
    UINT result = clip->ClientFormatListResponse(clip, &response);
    if (available && c->clipboard) c->clipboard(NULL, -1);
    return result;
}
static UINT clipboard_data_request(CliprdrClientContext* clip, const CLIPRDR_FORMAT_DATA_REQUEST* request) {
    Context* c = clip->custom;
    CLIPRDR_FORMAT_DATA_RESPONSE response = {
        .common.msgType = CB_FORMAT_DATA_RESPONSE, .common.msgFlags = CB_RESPONSE_FAIL };
    pthread_mutex_lock(&c->clip_lock);
    if (request->requestedFormatId == CF_UNICODETEXT && c->clip_data) {
        response.common.msgFlags = CB_RESPONSE_OK;
        response.common.dataLen = c->clip_length;
        response.requestedFormatData = c->clip_data;
    }
    UINT result = clip->ClientFormatDataResponse(clip, &response);
    pthread_mutex_unlock(&c->clip_lock);
    return result;
}
static UINT clipboard_data_response(CliprdrClientContext* clip, const CLIPRDR_FORMAT_DATA_RESPONSE* response) {
    Context* c = clip->custom;
    pthread_mutex_lock(&c->clip_lock);
    BOOL pending = c->clip_pending;
    BOOL current = c->request_generation == c->clip_generation;
    c->clip_pending = FALSE;
    pthread_mutex_unlock(&c->clip_lock);
    if (!pending) return CHANNEL_RC_OK;
    if (!current) {
        if (c->clipboard) c->clipboard(NULL, -1);
    } else if ((response->common.msgFlags & CB_RESPONSE_OK) && response->requestedFormatData &&
               response->common.dataLen >= 2 && response->common.dataLen <= CLIP_LIMIT &&
               response->common.dataLen % 2 == 0 && c->clipboard) {
        c->clipboard(response->requestedFormatData, (int)response->common.dataLen);
    }
    return CHANNEL_RC_OK;
}
static void clipboard_connected(Context* c, CliprdrClientContext* clip) {
    pthread_mutex_lock(&c->clip_lock);
    c->clip = clip;
    clip->custom = c;
    clip->MonitorReady = clipboard_ready;
    clip->ServerCapabilities = clipboard_caps;
    clip->ServerFormatList = clipboard_formats;
    clip->ServerFormatListResponse = clipboard_list_response;
    clip->ServerFormatDataRequest = clipboard_data_request;
    clip->ServerFormatDataResponse = clipboard_data_response;
    pthread_mutex_unlock(&c->clip_lock);
}
int urdp_clipboard(freerdp* f, const BYTE* data, unsigned length) {
    Context* c = (Context*)f->context;
    if (!data || length < 2 || length > CLIP_LIMIT || length % 2) return 0;
    BYTE* copy = malloc(length);
    if (!copy) return 0;
    memcpy(copy, data, length);
    pthread_mutex_lock(&c->clip_lock);
    if (c->clip_data) { memset(c->clip_data, 0, c->clip_length); free(c->clip_data); }
    c->clip_data = copy; c->clip_length = length;
    c->clip_generation++; c->remote_text = FALSE;
    UINT result = clipboard_offer(c);
    pthread_mutex_unlock(&c->clip_lock);
    return result == CHANNEL_RC_OK;
}
int urdp_clipboard_request(freerdp* f) {
    Context* c = (Context*)f->context;
    CLIPRDR_FORMAT_DATA_REQUEST request = { .common.msgType = CB_FORMAT_DATA_REQUEST,
        .requestedFormatId = CF_UNICODETEXT };
    pthread_mutex_lock(&c->clip_lock);
    UINT result = CHANNEL_RC_OK;
    if (c->clip && c->clip_ready && c->remote_text && !c->clip_pending) {
        c->clip_pending = TRUE; c->request_generation = c->clip_generation;
        result = c->clip->ClientFormatDataRequest(c->clip, &request);
    }
    pthread_mutex_unlock(&c->clip_lock);
    return result == CHANNEL_RC_OK;
}
