import { Schema } from 'mongoose';
import { mongoDbProvider } from '../mongoDBProvider';
import { IForm } from '../types';

export const formsScheme = new Schema<IForm>(
    {
        name: { type: String, required: true },
        title: { type: String },
        instructions: { type: String },
        // true on a registration form: the consent page is shown before the form (set by tools/setup_study.py)
        termsOfConditions: { type: Boolean },
        questions: Array<{ type: { type: string; required: true }; props: { type: object } }>,
    },
    { versionKey: false },
);

export const FormsModel = mongoDbProvider.getModel('forms', formsScheme);
