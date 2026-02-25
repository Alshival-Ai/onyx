import { Form, Formik } from "formik";
import { LLMProviderFormProps } from "../interfaces";
import * as Yup from "yup";
import {
  ProviderFormEntrypointWrapper,
  ProviderFormContext,
} from "./components/FormWrapper";
import { DisplayNameField } from "./components/DisplayNameField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { FormActionButtons } from "./components/FormActionButtons";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
  LLM_FORM_CLASS_NAME,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";

export const GEMINI_PROVIDER_NAME = "gemini";
const GEMINI_DISPLAY_NAME = "Google Gemini";
const DEFAULT_DEFAULT_MODEL_NAME = "gemini-2.5-pro";

export function GeminiForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName={GEMINI_DISPLAY_NAME}
      providerEndpoint={GEMINI_PROVIDER_NAME}
      existingLlmProvider={existingLlmProvider}
    >
      {({
        onClose,
        mutate,
        isTesting,
        setIsTesting,
        testError,
        setTestError,
        wellKnownLLMProvider,
      }: ProviderFormContext) => {
        const modelConfigurations = buildAvailableModelConfigurations(
          existingLlmProvider,
          wellKnownLLMProvider
        );
        const initialValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          api_key: existingLlmProvider?.api_key ?? "",
          default_model_name:
            existingLlmProvider?.default_model_name ??
            wellKnownLLMProvider?.recommended_default_model?.name ??
            DEFAULT_DEFAULT_MODEL_NAME,
          // Default to auto mode for new Gemini providers
          is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
        };

        const validationSchema = buildDefaultValidationSchema().shape({
          api_key: Yup.string().required("API Key is required"),
        });

        return (
          <Formik
            initialValues={initialValues}
            validationSchema={validationSchema}
            validateOnMount={true}
            onSubmit={async (values, { setSubmitting }) => {
              await submitLLMProvider({
                providerName: GEMINI_PROVIDER_NAME,
                values,
                initialValues,
                modelConfigurations,
                existingLlmProvider,
                shouldMarkAsDefault,
                setIsTesting,
                setTestError,
                mutate,
                onClose,
                setSubmitting,
              });
            }}
          >
            {(formikProps) => {
              return (
                <Form className={LLM_FORM_CLASS_NAME}>
                  <DisplayNameField disabled={!!existingLlmProvider} />

                  <PasswordInputTypeInField name="api_key" label="API Key" />

                  <DisplayModels
                    modelConfigurations={modelConfigurations}
                    formikProps={formikProps}
                    recommendedDefaultModel={
                      wellKnownLLMProvider?.recommended_default_model ?? null
                    }
                    shouldShowAutoUpdateToggle={true}
                  />

                  <AdvancedOptions formikProps={formikProps} />

                  <FormActionButtons
                    isTesting={isTesting}
                    testError={testError}
                    existingLlmProvider={existingLlmProvider}
                    mutate={mutate}
                    onClose={onClose}
                    isFormValid={formikProps.isValid}
                  />
                </Form>
              );
            }}
          </Formik>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
