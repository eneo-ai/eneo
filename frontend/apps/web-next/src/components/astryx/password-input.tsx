"use client";

import { Button } from "@astryxdesign/core/Button";
import { useState } from "react";
import { useTranslations } from "use-intl";
import { TextInput, type TextInputProps } from "./text-input";

/** A password field with an explicit reveal control that never submits its form. */
export function PasswordInput(props: Omit<TextInputProps, "type">) {
  const [visible, setVisible] = useState(false);
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-1">
      <TextInput {...props} type={visible ? "text" : "password"} />
      <Button
        label={t(visible ? "hide_password" : "show_password")}
        type="button"
        variant="ghost"
        size="sm"
        isDisabled={props.isDisabled}
        aria-pressed={visible}
        onClick={() => setVisible(!visible)}
        className="self-end"
      />
    </div>
  );
}
