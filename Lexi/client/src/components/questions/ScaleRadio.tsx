import { Grid, Radio, RadioGroup, Tooltip, Typography, useMediaQuery } from '@mui/material';
import { Box } from '@mui/system';
import theme from '@root/Theme';
import { getFormErrorMessage } from '@utils/commonFunctions';
import { Control, Controller, FieldErrors, FieldValues } from 'react-hook-form';

interface ScaleRadioProps {
    fieldKey: string;
    label?: string;
    left: string;
    right: string;
    range: number;
    required: boolean;
    gap?: string;
    numbered?: boolean;
    control?: Control<FieldValues>;
    errors: FieldErrors;
}

const ScaleRadio: React.FC<ScaleRadioProps> = ({
    fieldKey,
    label,
    left,
    right,
    range,
    required = false,
    numbered = false,
    gap = '0px',
    control,
    errors,
}) => {
    const valuesArray = Array.from({ length: range }, (_, i) => i + 1);
    const isMobile = useMediaQuery(theme.breakpoints.down('sm'));

    // On a phone the options share the full width of the screen (no fixed widths, nothing to scroll sideways).
    const groupStyle = isMobile
        ? { width: '100%', flexWrap: 'nowrap', justifyContent: 'space-between' }
        : { gap, justifyContent: 'flex-start' };
    const optionStyle = isMobile ? { flex: '1 1 0', minWidth: 0, textAlign: 'center' } : { textAlign: 'center' };
    const radioStyle = isMobile ? { padding: '6px 0' } : {};

    const options = (value?: string, onChange?: (event: React.ChangeEvent<HTMLInputElement>) => void) => (
        <RadioGroup row value={value} onChange={onChange} aria-label={fieldKey} sx={groupStyle}>
            {valuesArray.map((val) => (
                <Box key={val} sx={optionStyle}>
                    {numbered && <Typography variant="body2">{val}</Typography>}
                    {control ? (
                        <Radio
                            checked={value === String(val)}
                            onChange={onChange}
                            value={String(val)}
                            sx={radioStyle}
                            size="small"
                        />
                    ) : (
                        <Radio value={String(val)} sx={radioStyle} size="small" />
                    )}
                </Box>
            ))}
        </RadioGroup>
    );

    const radios = control ? (
        <Controller
            name={fieldKey || 'field'}
            control={control}
            rules={required ? { required: 'This field is required' } : {}}
            render={({ field: { onChange, value } }) => options(value, onChange)}
        />
    ) : (
        options()
    );

    const title = label && (
        <Typography style={{ color: 'grey', marginBottom: '8px', borderBottom: '1px solid grey' }}>
            {label} {required ? '*' : ''}
        </Typography>
    );

    const error = errors[fieldKey] && (
        <Typography color="error" variant="caption">
            {getFormErrorMessage(errors[fieldKey])}
        </Typography>
    );

    if (isMobile) {
        // Phone: the question, the options across the screen, and the two end labels underneath them.
        return (
            <Box style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
                {title}
                {radios}
                <Box style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                    <Typography variant="caption" color={'grey'} style={{ maxWidth: '48%' }}>
                        {left}
                    </Typography>
                    <Typography variant="caption" color={'grey'} style={{ maxWidth: '48%', textAlign: 'right' }}>
                        {right}
                    </Typography>
                </Box>
                {error}
            </Box>
        );
    }

    return (
        <Box style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
            {title}
            <Box key={left} style={{ display: 'flex', width: '100%', justifyContent: 'space-evenly' }}>
                <Grid
                    item
                    xs={2}
                    style={{
                        display: 'flex',
                        justifyContent: 'center',
                        paddingRight: '16px',
                        alignItems: numbered ? 'end' : 'center',
                        paddingBottom: numbered && '8px',
                    }}
                >
                    <Tooltip title={left}>
                        <Typography textAlign={'justify'} color={'grey'}>
                            {left}
                        </Typography>
                    </Tooltip>
                </Grid>
                <Grid
                    item
                    xs={8}
                    style={{
                        borderLeft: '1px solid #D3D3D3',
                        borderRight: '1px solid #D3D3D3',
                        display: 'flex',
                        justifyContent: 'center',
                        alignItems: 'center',
                    }}
                >
                    {radios}
                </Grid>
                <Grid
                    item
                    xs={2}
                    display={'flex'}
                    justifyContent={'center'}
                    alignItems={numbered ? 'end' : 'center'}
                    style={{
                        paddingLeft: '16px',
                        paddingBottom: numbered && '8px',
                    }}
                >
                    <Tooltip title={right}>
                        <Typography textAlign={'justify'} color={'grey'}>
                            {right}
                        </Typography>
                    </Tooltip>
                </Grid>
            </Box>
            {error}
        </Box>
    );
};

export default ScaleRadio;
