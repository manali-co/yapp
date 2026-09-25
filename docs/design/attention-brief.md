# Brief: the "attention" avatar state

Yapp gets a **parallel mode**: it works on a second display or the right half of the screen
while the user keeps working. Sometimes it must borrow the user's keyboard for well under a
second (a field that refuses Accessibility typing), or it needs an answer (an approval) while
the user is busy elsewhere.

Design an avatar state **attention** for those moments, in the existing system (tokens.css,
yapp-avatar.js STATES): distinct at a glance from listening/thinking/acting, warm rather than
alarming, with a clear "back to normal" transition. Copy lines it must carry:
"Borrowing your keyboard for a moment" → "Back to you"; "May I press Send in Mail? Say yes or
no" (an ask while the user is busy). The pill stays visible on the user's display even when
the work happens elsewhere. Deliver as an update to the design project bundle so it can be
ported byte-exact; the interim implementation maps attention to the acting spring plus copy.
