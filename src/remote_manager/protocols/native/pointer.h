/* Native pointer cache objects; Qt receives an owned RGBA snapshot. */
#include <freerdp/graphics.h>
#include <freerdp/codec/color.h>
typedef struct { rdpPointer base; BYTE* pixels; } Pointer;
static BOOL pointer_new(rdpContext* context, rdpPointer* p) {
    if (!p->width || !p->height || p->width > 512 || p->height > 512) return FALSE;
    Pointer* cursor = (Pointer*)p;
    cursor->pixels = calloc(p->width * p->height, 4);
    if (!cursor->pixels) return FALSE;
    if (!freerdp_image_copy_from_pointer_data(cursor->pixels, PIXEL_FORMAT_RGBA32, 0, 0, 0,
            p->width, p->height, p->xorMaskData, p->lengthXorMask,
            p->andMaskData, p->lengthAndMask, p->xorBpp, &context->gdi->palette)) {
        free(cursor->pixels); cursor->pixels = NULL; return FALSE;
    }
    return TRUE;
}
static void pointer_free(rdpContext* context, rdpPointer* p) { free(((Pointer*)p)->pixels); }
static BOOL pointer_set(rdpContext* context, rdpPointer* p) {
    Context* c = (Context*)context;
    if (c->pointer) c->pointer(((Pointer*)p)->pixels, p->width, p->height, p->xPos, p->yPos);
    return TRUE;
}
static BOOL pointer_null(rdpContext* context) {
    Context* c = (Context*)context;
    if (c->pointer) c->pointer(NULL, -1, 0, 0, 0);
    return TRUE;
}
static BOOL pointer_default(rdpContext* context) {
    Context* c = (Context*)context;
    if (c->pointer) c->pointer(NULL, 0, 0, 0, 0);
    return TRUE;
}
static BOOL pointer_position(rdpContext* context, UINT32 x, UINT32 y) {
    /* Do not warp the user's desktop pointer (unsupported on native Wayland). */
    return TRUE;
}
static void register_pointer(rdpContext* context) {
    rdpPointer p = { 0 };
    p.size = sizeof(Pointer);
    p.New = pointer_new; p.Free = pointer_free; p.Set = pointer_set;
    p.SetNull = pointer_null; p.SetDefault = pointer_default; p.SetPosition = pointer_position;
    graphics_register_pointer(context->graphics, &p);
}
