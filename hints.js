/* North Sea Surf: what the app teaches, and when (app.js's hint controller).

   One entry a hint. Words are i18n.js keys, never the words themselves, and
   the control is found by its data-hint-target, so the panel's markup can
   change freely. A tip shows once, when its `when` is met:
     first-load              the first run is on the chart
     after:<id>              that hint has gone (a chain: one hint a visit)
   and goes for good when its doneEvent fires (app.js emits them), when it's
   tapped, or after a while untouched. Registry order is the order they're
   offered in. */
'use strict';

const HINTS = [
  { id: 'tip.timeline.slide', type: 'tip', target: 'timeline', when: 'first-load', label: 'tipSlide', icon: 'slide', doneEvent: 'timeline.drag' },
  { id: 'tip.timeline.reset', type: 'tip', target: 'timeline', when: 'after:tip.timeline.slide', label: 'tipReset', icon: 'reset', doneEvent: 'timeline.reset' }
];
