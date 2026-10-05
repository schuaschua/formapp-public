// FORM-230 (spine AD-19 "Client"): the public surface of the one Speech SDK boundary. Nothing
// outside `web/src/speech/` imports `microsoft-cognitiveservices-speech-sdk`, `recognizer.ts` or
// `tokenCache.ts` directly -- only this hook.
export {
  useMicRecognition,
  type MicErrorReason,
  type UseMicRecognitionOptions,
  type UseMicRecognitionResult,
} from "./useMicRecognition";
