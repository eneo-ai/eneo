/**
 * For a dialog the software keyboard rises over: on a touch screen it hangs
 * from the top, clear of the notch, instead of centring, so its field and
 * buttons stay above the keyboard. A Tailwind utility, so it beats the
 * dialog's own StyleX margin (the utilities layer comes last).
 */
export const DIALOG_TOP_ON_TOUCH = "pointer-coarse:mt-[max(1rem,env(safe-area-inset-top,0px))]";
