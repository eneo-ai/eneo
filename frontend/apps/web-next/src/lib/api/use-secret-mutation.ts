import {
  useMutation,
  type DefaultError,
  type MutationFunctionContext,
  type UseMutationOptions,
  type UseMutationResult
} from "@tanstack/react-query";
import { useRef } from "react";

type SecretMutationOptions<TData, TError, TVariables, TOnMutateResult> = Omit<
  UseMutationOptions<TData, TError, TVariables, TOnMutateResult>,
  "mutationFn"
> & {
  mutationFn: (variables: TVariables, context: MutationFunctionContext) => Promise<TData>;
};

type SecretMutationResult<TData, TError, TVariables, TOnMutateResult> = Omit<
  UseMutationResult<TData, TError, void, TOnMutateResult>,
  "mutate" | "mutateAsync" | "variables"
> & {
  mutate: (variables: TVariables) => void;
  mutateAsync: (variables: TVariables) => Promise<TData>;
};

/**
 * `useMutation` for a call whose variables carry a secret (an API key, a
 * password, a client secret, a token). React Query keeps a mutation's
 * variables in its cache after it has settled, so these never reach it:
 * `mutate(variables)` holds them here while the call runs, the options'
 * callbacks get them as usual, and they are dropped once it has settled.
 * A secret in the response is the caller's to keep out (`withoutSecret`).
 */
export function useSecretMutation<
  TData = unknown,
  TError = DefaultError,
  TVariables = void,
  TOnMutateResult = unknown
>({
  mutationFn,
  onMutate,
  onSuccess,
  onError,
  onSettled,
  ...options
}: SecretMutationOptions<TData, TError, TVariables, TOnMutateResult>): SecretMutationResult<
  TData,
  TError,
  TVariables,
  TOnMutateResult
> {
  // ponytail: one call at a time, as every caller ignores presses while one
  // runs; a call started meanwhile would take over the first one's variables.
  const held = useRef<{ variables: TVariables } | null>(null);
  const variables = () => held.current!.variables;
  const { mutate, mutateAsync, ...mutation } = useMutation<TData, TError, void, TOnMutateResult>({
    ...options,
    mutationFn: (_, context) => mutationFn(variables(), context),
    onMutate: onMutate && ((_, context) => onMutate(variables(), context)),
    onSuccess:
      onSuccess && ((data, _, result, context) => onSuccess(data, variables(), result, context)),
    onError:
      onError && ((error, _, result, context) => onError(error, variables(), result, context)),
    onSettled: async (data, error, _, result, context) => {
      try {
        await onSettled?.(data, error, variables(), result, context);
      } finally {
        held.current = null;
      }
    }
  });
  return {
    ...mutation,
    mutate: (next) => {
      held.current = { variables: next };
      mutate();
    },
    mutateAsync: (next) => {
      held.current = { variables: next };
      return mutateAsync();
    }
  };
}
