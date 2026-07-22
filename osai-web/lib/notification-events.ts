export const NOTIFICATIONS_CHANGED_EVENT = "sheldon:notifications-changed";

export function announceNotificationsChanged(unreadCount?: number) {
  window.dispatchEvent(
    new CustomEvent(NOTIFICATIONS_CHANGED_EVENT, { detail: { unreadCount } })
  );
}
