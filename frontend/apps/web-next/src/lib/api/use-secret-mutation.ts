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
  UseMutationResult<TData, TError, number, TOnMutateResult>,
  "mutate" | "mutateAsync" | "variables"
> & {
  mutate: (variables: TVariables) => void;
  mutateAsync: (variables: TVariables) => Promise<TData>;
};

/**
 * `useMutation` for a call whose variables carry a secret (an API key, a
 * password, a client secret, a token). React Query keeps a mutation's
 * variables in its cache after it has settled, so these never reach it: each
 * `mutate(variables)` gets its own id, React Query sees only that id, and the
 * variables are held here under it while the call runs. The options'
 * callbacks get them as usual, each call its own, also when a second call
 * starts before the first has settled; they are dropped once it has settled.
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
  const held = useRef(new Map<number, TVariables>());
  const lastCall = useRef(0);
  const variables = (call: number) => held.current.get(call) as TVariables;
  const { mutate, mutateAsync, ...mutation } = useMutation<TData, TError, number, TOnMutateResult>({
    ...options,
    mutationFn: (call, context) => mutationFn(variables(call), context),
    onMutate: onMutate && ((call, context) => onMutate(variables(call), context)),
    onSuccess:
      onSuccess &&
      ((data, call, result, context) => onSuccess(data, variables(call), result, context)),
    onError:
      onError &&
      ((error, call, result, context) => onError(error, variables(call), result, context)),
    onSettled: async (data, error, call, result, context) => {
      try {
        await onSettled?.(data, error, variables(call), result, context);
      } finally {
        held.current.delete(call);
      }
    }
  });
  const start = (next: TVariables) => {
    const call = ++lastCall.current;
    held.current.set(call, next);
    return call;
  };
  return {
    ...mutation,
    mutate: (next) => mutate(start(next)),
    mutateAsync: (next) => mutateAsync(start(next))
  };
}
