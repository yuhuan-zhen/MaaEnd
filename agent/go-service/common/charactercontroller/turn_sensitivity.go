package charactercontroller

import (
	"os"
	"strconv"
	"strings"

	"github.com/MaaXYZ/maa-framework-go/v4"
	"github.com/rs/zerolog/log"

	"github.com/MaaXYZ/MaaEnd/agent/go-service/pkg/pienv"
)

// 视角转向灵敏度：1 度偏航对应多少「相对位移单位」。
//
// 不同控制器的单位空间不一样，不能共用一个乘数：
//
//   - desktop（Win32 hover 等）：1 度 = 2 屏幕像素横向拖动，这是原 base 标定。
//     注意 MapNavigator 的 kTurn360UnitsPerWidth（≈7.93 单位/度）是另一套坐标系，
//     不经过本函数，两者不能互相代入。
//   - 云网页客户端（官网页面内的转向实现）：实测 3.87 单位/度，取协议值 4.0。
//     依据 tools/pr6696-tests/T5i-灵敏度与上限实测.md：60/90/100 单位三点线性段
//     给出 3.64/3.85/4.16，拆段 360 单位实测 94.0°；同一份实测还确认单次位移上限
//     约 126 单位（≈32°），因此下游必须拆段发送（见 _MAX_RELATIVE_STEP）。
//   - 触摸（ADB / PlayCover / 原生安卓）：3.0，对齐 kAdbTouchTurnProfile.default_units_per_degree。
//
// 环境变量 MAA_TURN_UNITS_PER_DEGREE 可直接钉死数值，用于现场重新标定而不必重编。
const (
	desktopTurnUnitsPerDegree  = 2.0
	cloudWebTurnUnitsPerDegree = 4.0
	touchTurnUnitsPerDegree    = 3.0

	envTurnUnitsPerDegree = "MAA_TURN_UNITS_PER_DEGREE"

	// 云网页控制器在 GetInfo() 里自报的特征串（见 cdp_controller.get_custom_info）。
	cloudWebControllerMarker = "cdp-pipe"
	cloudWebControllerName   = "cloudweb"
)

// turnUnitsPerDegree 返回当前控制器的水平转向灵敏度。
func turnUnitsPerDegree(ctrl *maa.Controller) float64 {
	if raw := strings.TrimSpace(os.Getenv(envTurnUnitsPerDegree)); raw != "" {
		if value, err := strconv.ParseFloat(raw, 64); err == nil && value > 0 {
			return value
		}
		log.Warn().Str("raw", raw).Str("env", envTurnUnitsPerDegree).
			Msg("invalid turn units per degree, falling back to controller default")
	}
	if isCloudWebController(ctrl) {
		return cloudWebTurnUnitsPerDegree
	}
	if pienv.IsAdbLikeControllerType(pienv.ResolveControllerKind(ctrl)) {
		return touchTurnUnitsPerDegree
	}
	return desktopTurnUnitsPerDegree
}

// pitchUnitsPerDegree 返回纵向灵敏度。
// 纵向尚未单独标定（T5i 只覆盖水平方向），但同一个客户端用同一套换算，
// 因此与水平保持一致；等纵向实测数据到位后再拆开。
func pitchUnitsPerDegree(ctrl *maa.Controller) float64 {
	return turnUnitsPerDegree(ctrl)
}

// isCloudWebController 判断是否为云网页控制器：它在 GetInfo() 里报 transport=cdp-pipe。
func isCloudWebController(ctrl *maa.Controller) bool {
	if ctrl == nil {
		return false
	}
	info, err := ctrl.GetInfo()
	if err != nil {
		return false
	}
	lower := strings.ToLower(info)
	return strings.Contains(lower, cloudWebControllerMarker) ||
		strings.Contains(lower, cloudWebControllerName)
}

// resolveController 按仓库既有约定取控制器：PI_CONTROLLER 已给出类别时不碰句柄，
// 仅在缺失时向 tasker 兜底一次（参见 bettersliding / autofight 的同名处理）。
func resolveController(ctx *maa.Context) *maa.Controller {
	if pienv.ControllerKind() != pienv.ControllerKindUnknown {
		return nil
	}
	if ctx == nil || ctx.GetTasker() == nil {
		return nil
	}
	return ctx.GetTasker().GetController()
}
