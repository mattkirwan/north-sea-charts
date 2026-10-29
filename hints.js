/* North Sea Surf: what the app teaches, and when (app.js's hint controller).

   One entry a hint. Words are i18n.js keys, never the words themselves, and
   the control is found by its data-hint-target, so the panel's markup can
   change freely. A tip shows once, when its `when` is met:
     first-load              the first run is on the chart
     after:<id>              that hint has gone (a chain: one hint a visit)
     measure:<var>           Swell is on the chart, showing height or period
   and goes for good when its doneEvent fires (app.js emits them), when it's
   tapped, or after a while untouched. With a `point` (a data-hint-point
   inside the control) it floats over that part, notched to it, rather than
   sitting in the control.

   A new feature (type 'new') lights its control and the way to it through
   the menu (`path`, data-hint-targets, outermost first), and once shows a
   tag that opens a card (kicker, title, body; Show me runs `action`, in
   app.js). Only for people who first came before `since`, the day it was
   merged to main. Ignored, it stays lit; used, it's gone. Kept for key
   features only, each added on purpose when Matt asks for it: none at
   present (tests/test_app.py tries the layer with one of its own).

   Registry order is the order they're offered in: the tip for a control
   just used first, as only using it makes it due; then the others; then new
   features, oldest first. */
'use strict';

const HINTS = [
  { id: 'tip.swell.period', type: 'tip', target: 'swell', point: 'period', when: 'measure:height', label: 'tipPeriod', icon: 'period', doneEvent: 'swell.measure' },
  { id: 'tip.timeline.slide', type: 'tip', target: 'timeline', when: 'first-load', label: 'tipSlide', icon: 'slide', doneEvent: 'timeline.drag' },
  { id: 'tip.timeline.reset', type: 'tip', target: 'timeline', when: 'after:tip.timeline.slide', label: 'tipReset', icon: 'reset', doneEvent: 'timeline.reset' }
];
