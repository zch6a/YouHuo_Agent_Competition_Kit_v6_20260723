/* Bottom sheet for the elder screen.
 *
 * The dismissal rule is taken from Framework7's sheet-class.js, which is the
 * most-copied mobile-web sheet there is:
 *
 *     if ((timeDiff < 300 && diff > 20) || (timeDiff >= 300 && diff > height / 2))
 *
 * A flick under 300ms needs only 20px; a slow drag has to commit past half the
 * sheet. That combination is why a good sheet feels neither sticky nor twitchy,
 * and it happens to be exactly right for this audience: almost no force is
 * needed to dismiss deliberately, while a hesitant, wandering finger cannot
 * dismiss by accident.
 *
 * Written in vanilla JS on purpose. Motion or Swiper would each do this, but the
 * settle is an overdamped curve a CSS transition already expresses, and pointer
 * tracking is the twenty lines below — a ~30KB dependency for that would be paid
 * for by every elder on mobile data, on a free-tier server, for nothing.
 *
 * The sheet is never gesture-only: it opens and closes from a real labelled
 * button. Gesture-only UI fails this audience first.
 */
(function () {
  'use strict';

  const sheet = document.querySelector('#extrasSheet');
  const backdrop = document.querySelector('#sheetBackdrop');
  const openers = document.querySelectorAll('[data-sheet-open]');
  const closers = document.querySelectorAll('[data-sheet-close]');
  if (!sheet || !backdrop) return;

  const FLICK_MS = 300;
  const FLICK_PX = 20;
  let dragging = false;
  let startY = 0;
  let startTime = 0;
  let offset = 0;
  let lastFocus = null;

  function setOpen(open) {
    sheet.classList.toggle('is-open', open);
    backdrop.classList.toggle('is-open', open);
    sheet.setAttribute('aria-hidden', open ? 'false' : 'true');
    // inert rather than display:none so the panel stays in the layout: the
    // contrast audit measures computed colours of these controls, and hiding
    // them would quietly shrink that safety net instead of failing loudly.
    if (open) sheet.removeAttribute('inert'); else sheet.setAttribute('inert', '');
    openers.forEach(b => b.setAttribute('aria-expanded', open ? 'true' : 'false'));
    document.body.classList.toggle('sheet-open', open);
    if (open) {
      lastFocus = document.activeElement;
      const first = sheet.querySelector('button, a, select, input');
      if (first) first.focus({preventScroll: true});
    } else if (lastFocus) {
      lastFocus.focus({preventScroll: true});
      lastFocus = null;
    }
  }

  function endDrag(commitClose) {
    dragging = false;
    sheet.style.transition = '';
    sheet.style.transform = '';
    if (commitClose) setOpen(false);
  }

  sheet.addEventListener('pointerdown', event => {
    // Only the handle drags. Dragging from anywhere would fight the scrollable
    // list inside, which is the usual reason home-made sheets feel broken.
    if (!event.target.closest('.sheet-handle')) return;
    dragging = true;
    startY = event.clientY;
    startTime = Date.now();
    offset = 0;
    sheet.style.transition = 'none';
    sheet.setPointerCapture?.(event.pointerId);
  });

  sheet.addEventListener('pointermove', event => {
    if (!dragging) return;
    offset = Math.max(0, event.clientY - startY);   // downward only
    sheet.style.transform = `translate3d(0, ${offset}px, 0)`;
  });

  sheet.addEventListener('pointerup', () => {
    if (!dragging) return;
    const elapsed = Date.now() - startTime;
    const flicked = elapsed < FLICK_MS && offset > FLICK_PX;
    const dragged = elapsed >= FLICK_MS && offset > sheet.offsetHeight / 2;
    endDrag(flicked || dragged);
  });
  sheet.addEventListener('pointercancel', () => endDrag(false));

  openers.forEach(b => b.addEventListener('click', () => setOpen(true)));
  closers.forEach(b => b.addEventListener('click', () => setOpen(false)));
  backdrop.addEventListener('click', () => setOpen(false));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && sheet.classList.contains('is-open')) setOpen(false);
  });

  setOpen(false);
})();
