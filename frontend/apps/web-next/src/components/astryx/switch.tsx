"use client";

import {
  Switch as AstryxSwitch,
  type SwitchProps as AstryxSwitchProps
} from "@astryxdesign/core/Switch";

/**
 * Astryx Switch without its busy state. Astryx 0.6.3 announces a hard-coded
 * English "Loading" while `isLoading` is set or a `changeAction` is pending,
 * so those props are left out; a switch that saves on toggle uses
 * `useSettingSwitch` (optimistic, reverts on error) instead. Lint sends every
 * Switch import here.
 */
export type SwitchProps = Omit<AstryxSwitchProps, "isLoading" | "changeAction">;

export function Switch(props: SwitchProps) {
  return <AstryxSwitch {...props} />;
}
