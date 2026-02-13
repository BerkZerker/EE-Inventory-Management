import { useState, useCallback } from "react";

export function useForm<T extends Record<string, unknown>>(initialValues: T) {
  const [values, setValues] = useState<T>(initialValues);

  const handleChange = useCallback((field: keyof T, value: T[keyof T]) => {
    setValues(prev => ({ ...prev, [field]: value }));
  }, []);

  const reset = useCallback((newValues?: T) => {
    setValues(newValues ?? initialValues);
  }, [initialValues]);

  return { values, setValues, handleChange, reset };
}
