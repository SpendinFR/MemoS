Shader "MLOmega/XREAL FreeGuy Mesh"
{
    Properties
    {
        _BaseColor ("Base", Color) = (0.05, 0.82, 1.0, 0.055)
        _GridColor ("Grid", Color) = (0.35, 1.0, 0.8, 0.22)
        _GridScale ("Grid scale", Float) = 2.4
        _ScanSpeed ("Scan speed", Float) = 0.55
    }
    SubShader
    {
        Tags
        {
            "Queue" = "Transparent+5"
            "RenderType" = "Transparent"
            "RenderPipeline" = "UniversalPipeline"
        }
        Pass
        {
            Name "FreeGuyWorld"
            Tags { "LightMode" = "UniversalForward" }
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            ZTest LEqual
            Cull Back

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_instancing
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            struct Attributes
            {
                float3 positionOS : POSITION;
                float3 normalOS : NORMAL;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 positionWS : TEXCOORD0;
                float3 normalWS : TEXCOORD1;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            half4 _BaseColor;
            half4 _GridColor;
            float _GridScale;
            float _ScanSpeed;

            Varyings Vert(Attributes input)
            {
                Varyings output;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
                VertexPositionInputs pos = GetVertexPositionInputs(input.positionOS);
                output.positionCS = pos.positionCS;
                output.positionWS = pos.positionWS;
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                return output;
            }

            half4 Frag(Varyings input) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);
                float3 gridUVW = abs(frac(input.positionWS * _GridScale) - 0.5);
                float grid = 1.0 - smoothstep(0.44, 0.49, min(min(gridUVW.x, gridUVW.y), gridUVW.z));
                float scan = pow(saturate(1.0 - abs(frac(
                    input.positionWS.y * 0.28 - _Time.y * _ScanSpeed) - 0.5) * 2.0), 16.0);
                float fresnel = pow(1.0 - saturate(dot(
                    normalize(input.normalWS),
                    normalize(_WorldSpaceCameraPos - input.positionWS))), 2.0);
                half4 color = lerp(_BaseColor, _GridColor, saturate(grid * 0.35 + scan + fresnel * 0.45));
                color.a = saturate(_BaseColor.a + grid * 0.05 + scan * 0.16 + fresnel * 0.08);
                return color;
            }
            ENDHLSL
        }
    }
    Fallback Off
}
