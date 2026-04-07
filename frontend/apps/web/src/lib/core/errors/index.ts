/**
 * Centralized error handling utilities for Eneo.
 *
 * Maps backend error codes to localized i18n messages, providing
 * consistent error messages across the entire application.
 *
 * ## How it works
 *
 * 1. Backend raises an exception with a specific ErrorCode (e.g. 9033)
 * 2. Frontend receives the error with error.code = 9033
 * 3. getErrorMessage() maps 9033 → m.eneo_error_9033() (localized message)
 * 4. If no mapping exists, falls back to the backend's English message
 *
 * ## Adding support for a new error code
 *
 * When a new ErrorCode is added in the backend (backend/src/intric/main/exceptions.py),
 * three steps are required to get localized error messages in the frontend:
 *
 * 1. Add i18n messages in BOTH language files:
 *    - frontend/apps/web/messages/en.json → "eneo_error_{code}": "English message"
 *    - frontend/apps/web/messages/sv.json → "eneo_error_{code}": "Swedish message"
 *
 * 2. Add the mapping in getErrorMessage.ts:
 *    - {code}: () => m.eneo_error_{code}()
 *
 * 3. Done! All components using toastError() or getErrorMessage() will
 *    automatically show the localized message for this error code.
 *
 * Without these steps, the error will fall back to the backend's English
 * message — functional but not localized.
 */
export { getErrorMessage } from "./getErrorMessage";
export { toastError } from "./toastError";
