## Over Auto

Provides for both automatic control of a device and for manual override of that automatic control.

Say you want a bathroom fan to come on when the humidity exceeds some threshold. Easy enough, one trigger to turn it on and one to turn it off.

You can still turn the fan on at the switch, but to keep the automatic triggers from turning it back off you'll need actions to disable (and later re-enable) them.  And if you want it to revert to automatic control at some point, you'll need a timer and another trigger - and a way to evaluate if it 'should' be on or off when the timer expires. Still not a big deal.

If you want all this to work the same way when you turn the switch off, just do everything again for the other state.

Now say you also want to override the automatic control of the fan from from a control page. Repeat again for the control page control on and off.

What if you also want to cancel the override when you leave the house?  Even more triggers.

This is all perfectly do-able with Indigo, but after setting it up twice I decided to write a plugin to manage it all instead.  

Much simpler.
