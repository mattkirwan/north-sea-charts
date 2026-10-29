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
   sitting in the control. Registry order is the order they're offered in:
   the one for a control just used first, as only using it makes it due. */
'use strict';

const HINTS = [
  { id: 'tip.swell.period', type: 'tip', target: 'swell', point: 'period', when: 'measure:height', label: 'tipPeriod', icon: 'period', doneEvent: 'swell.measure' },
  { id: 'tip.timeline.slide', type: 'tip', target: 'timeline', when: 'first-load', label: 'tipSlide', icon: 'slide', doneEvent: 'timeline.drag' },
  { id: 'tip.timeline.reset', type: 'tip', target: 'timeline', when: 'after:tip.timeline.slide', label: 'tipReset', icon: 'reset', doneEvent: 'timeline.reset' }
];
