import { useState, useCallback } from "react";

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useAsync<T>(initialData: T | null = null) {
  const [state, setState] = useState<AsyncState<T>>({
    data: initialData,
    loading: false,
    error: null,
  });

  const execute = useCallback(async (asyncFn: () => Promise<T>) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const data = await asyncFn();
      setState({ data, loading: false, error: null });
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : "An error occurred";
      setState(prev => ({ ...prev, loading: false, error: message }));
      throw err;
    }
  }, []);

  const setData = useCallback((data: T | null) => {
    setState(prev => ({ ...prev, data }));
  }, []);

  const setError = useCallback((error: string | null) => {
    setState(prev => ({ ...prev, error }));
  }, []);

  return { ...state, execute, setData, setError };
}
