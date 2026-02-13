import { AxiosError } from "axios";

export function extractErrorMessage(err: unknown, fallback = "An error occurred"): string {
  if (err instanceof AxiosError && err.response?.data?.error) {
    return err.response.data.error;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return fallback;
}
