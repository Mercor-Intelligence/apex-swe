import Medusa from "@medusajs/js-sdk";
import { config } from "dotenv";
import { z, ZodTypeAny } from "zod";
import storeJson from "../oas/store.json";
import { SdkRequestType, StoreJson, Parameter } from "../types/store-json";
import { defineTool, InferToolHandlerInput } from "../utils/define-tools";

config();

const MEDUSA_BACKEND_URL =
    process.env.MEDUSA_BACKEND_URL ?? "http://localhost:9000";

export default class MedusaStoreService {
    sdk: Medusa;
    constructor(
        medusaBackendUrl: string = MEDUSA_BACKEND_URL,
        apiKey: string = process.env.PUBLISHABLE_KEY ?? ""
    ) {
        this.sdk = new Medusa({
            baseUrl: medusaBackendUrl ?? MEDUSA_BACKEND_URL,
            debug: process.env.NODE_ENV === "development",
            publishableKey: apiKey ?? process.env.PUBLISHABLE_KEY,
            auth: {
                type: "session"
            }
        });
    }

    wrapPath(refPath: string, refFunction: SdkRequestType) {
        return defineTool((z): any => {
            let name;
            let description;
            let parameters: Parameter[] = [];
            let method = "get";
            const anyRef = refFunction as any;
            if ("get" in refFunction) {
                method = "get";
                name = refFunction.get.operationId;
                description = refFunction.get.description;
                parameters = refFunction.get.parameters;
            } else if ("post" in refFunction) {
                method = "post";
                name = refFunction.post.operationId;
                description = refFunction.post.description;
                parameters = refFunction.post.parameters ?? [];
            } else if ("delete" in anyRef) {
                method = "delete";
                name = anyRef.delete.operationId;
                description = anyRef.delete.description;
                parameters = anyRef.delete.parameters ?? [];
            }
            if (!name) {
                throw new Error(`No name found for path: ${refPath}`);
            }

            const paramSchema = parameters
                .filter((p) => p.in != "header")
                .reduce((acc, param) => {
                    switch (param.schema.type) {
                        case "string":
                            acc[param.name] = z.string().optional();
                            break;
                        case "number":
                            acc[param.name] = z.number().optional();
                            break;
                        case "boolean":
                            acc[param.name] = z.boolean().optional();
                            break;
                        case "array":
                            acc[param.name] = z
                                .array(z.string())
                                .optional();
                            break;
                        case "object":
                            acc[param.name] = z.object({}).optional();
                            break;
                        default:
                            acc[param.name] = z.string().optional();
                    }
                    return acc;
                }, {} as any);

            // For POST/DELETE, add common body field validators
            const bodySchema = method !== "get" ? {
                email: z.string().optional(),
                password: z.string().optional(),
                first_name: z.string().optional(),
                last_name: z.string().optional(),
                phone: z.string().optional(),
                company: z.string().optional(),
                address_1: z.string().optional(),
                address_2: z.string().optional(),
                city: z.string().optional(),
                country_code: z.string().optional(),
                province: z.string().optional(),
                postal_code: z.string().optional(),
                metadata: z.record(z.unknown()).optional(),
                // Catch-all for other common fields
                ...Object.fromEntries(
                    ['items', 'shipping_address', 'billing_address', 'context', 'region_id'].map(k => [k, z.unknown().optional()])
                )
            } : {};

            return {
                name: name!,
                description: description,
                inputSchema: {
                    ...paramSchema,
                    ...bodySchema
                },

                handler: async (
                    input: InferToolHandlerInput<any, ZodTypeAny>
                ): Promise<any> => {
                    const queryParamNames = (parameters || [])
                        .filter((p) => p.in === "query")
                        .map((p) => p.name);
                    
                    const pathParamNames = (parameters || [])
                        .filter((p) => p.in === "path")
                        .map((p) => p.name);

                    // Replace path parameters in URL
                    let finalPath = refPath;
                    for (const paramName of pathParamNames) {
                        const value = (input as any)[paramName];
                        if (value !== undefined && value !== null) {
                            finalPath = finalPath.replace(`{${paramName}}`, String(value));
                        }
                    }

                    const query = new URLSearchParams();
                    for (const name of queryParamNames) {
                        const value = (input as any)[name];
                        if (value === undefined || value === null) continue;
                        if (Array.isArray(value)) {
                            for (const v of value) query.append(name, String(v));
                        } else {
                            query.set(name, String(value));
                        }
                    }

                    // Build body from remaining inputs (exclude query/header/path params)
                    const body: Record<string, any> = {};
                    if (method !== "get") {
                        for (const [key, value] of Object.entries(input as any)) {
                            if (queryParamNames.includes(key)) continue;
                            if (pathParamNames.includes(key)) continue;
                            body[key] = value;
                        }
                    }

                    if (method === "get") {
                        console.error(
                            `Fetching ${finalPath} with GET ${query.toString()}`
                        );
                    }

                    const response = await this.sdk.client.fetch(finalPath, {
                        method: method,
                        headers: {
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "Authorization": `Bearer ${process.env.PUBLISHABLE_KEY}`
                        },
                        query,
                        ...(method === "get" ? {} : { body })
                    });
                    return response;
                }
            };
        });
    }

    defineTools(store = storeJson): any[] {
        const paths = Object.entries(store.paths) as [string, SdkRequestType][];
        const tools: any[] = [];
        
        for (const [path, refFunction] of paths) {
            const anyRef = refFunction as any;
            // Process each HTTP method separately, checking for operationId
            if (anyRef.get && anyRef.get.operationId) {
                tools.push(this.wrapPath(path, { get: anyRef.get } as any));
            }
            if (anyRef.post && anyRef.post.operationId) {
                tools.push(this.wrapPath(path, { post: anyRef.post } as any));
            }
            if (anyRef.delete && anyRef.delete.operationId) {
                tools.push(this.wrapPath(path, { delete: anyRef.delete } as any));
            }
        }
        
        return tools;
    }
}
