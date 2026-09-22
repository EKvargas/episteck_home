import { DataEnvelope } from '../state/DataEnvelope';

export interface AdapterContract<TArgs, TResult> {
  (args: TArgs): Promise<DataEnvelope<TResult>>;
}
