/**
 * Turn any API failure into a string that is safe to render.
 *
 * FastAPI answers a rejected request body with `detail` as an *array* of
 * validation objects, not a string. Passing that straight into state and
 * rendering it throws "Objects are not valid as a React child", which unmounts
 * the tree — the screen goes black and the real error is never shown. A teacher
 * pressing START CLASS saw exactly that: a blank classroom instead of a message
 * telling them what was wrong.
 *
 * An error message is the last thing that should be able to break a page, so
 * everything is flattened to text here and the fallback is always used when
 * there is nothing readable to show.
 */
export function apiError(err, fallback = 'Something went wrong. Please try again.') {
  const detail = err?.response?.data?.detail;

  if (typeof detail === 'string' && detail.trim()) return detail;

  // 422: [{ loc: ["body", "subject"], msg: "Field required", … }, …]
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item;
        const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : null;
        const msg = item?.msg || item?.message;
        if (!msg) return null;
        return field ? `${field}: ${msg}` : msg;
      })
      .filter(Boolean);
    if (messages.length) return messages.join('; ');
  }

  if (detail && typeof detail === 'object') {
    const msg = detail.msg || detail.message || detail.error;
    if (typeof msg === 'string' && msg.trim()) return msg;
  }

  const message = err?.response?.data?.message;
  if (typeof message === 'string' && message.trim()) return message;

  return fallback;
}

export default apiError;
