export type LLMModelPriceRead = {
  id: string;
  provider: string;
  model: string;
  inputUsdPer1mTokens: string | number;
  outputUsdPer1mTokens: string | number;
  cacheReadUsdPer1mTokens: string | number | null;
  cacheWriteUsdPer1mTokens: string | number | null;
  createdAt: string;
  updatedAt: string;
};

export type ProviderModel = {
  id: string;
  name: string;
};
