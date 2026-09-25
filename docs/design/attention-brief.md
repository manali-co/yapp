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


# Brief: the working glow and Yapp's cursor

Around every window Yapp is acting in (both modes) it draws a soft rounded frame in the
avatar's acting hue (oklch 70% 0.06 45), 10 px outside the window edge, 3 px stroke with a
16 px blur, following the window when it moves. Steady while acting, pulsing at the pulse
duration while Yapp needs the user (attention), fading over the settle duration when done,
gone at clean-up. Inside it Yapp may draw its own cursor: a 10 px dot in the same hue with
a white centre, marking where a virtual click was delivered (the user's cursor never moves).
Please confirm or adjust stroke, blur, radius (14 px), pulse alpha range (0.45–1.0) and the
dot, and whether the light appearance wants a darker stroke. Implementation reads L/C/h from
yapp-avatar.js and the durations from tokens.css, so a bundle update is enough to retune it.
